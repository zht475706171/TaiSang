"""Agent 工具实现。

每个工具:
- schema(): 返回 OpenAI function schema
- run(args): 执行,返回 dict observation

工具集(ToolRegistry 注册 6 个工具):
- read_file(path) — 读文件
- grep(pattern, scope) — 正则搜
- glob(pattern) — 文件名匹配
- Edit(file_path, old_string, new_string) — 改文件(经用户确认)
- Write(file_path, content) — 创建/覆盖文件(经用户确认)
- Bash(command) — 执行白名单 shell 命令(cwd 限定在 source_root)

安全:
- ReadFileTool/GrepTool/EditTool/WriteTool 对 path 做 containment 校验,拒绝越界访问
- EditTool/WriteTool 改文件前调用 confirmer,默认 AutoDenyConfirmer(拒绝所有)
- GrepTool 的 regex.search 有超时保护(Linux/Mac via signal.SIGALRM,Windows 跳过)
- BashTool 用命令前缀白名单 + cwd 限定 + subprocess 超时,输出截断保护
"""

from __future__ import annotations

import fnmatch
import logging
import re
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from ..storage.paths import PathManager
from .confirm import AutoDenyConfirmer

log = logging.getLogger(__name__)

# regex search 超时秒数(仅 Linux/Mac 生效,Windows 跳过)
_REGEX_TIMEOUT = 5.0

# Bash 合并输出内联上限(对齐 Claude Code BashTool)。超长落盘到 .code-reader/observations/。
BASH_MAX_OUTPUT = 30_000
# 落盘时给 agent 的预览字节数。
BASH_PREVIEW_BYTES = 2000

# Glob 硬切上限(对齐 Claude Code GlobTool)。
MAX_GLOB_RESULTS = 100

# Grep 跳过超长行(对齐 Claude Code --max-columns,防 minified/base64 行 DoS)。
MAX_LINE_LENGTH = 500


def _rel(source_root: Path, path: Path) -> str:
    """返回相对 source_root 的 Unix 风格路径。消除重复的 relative_to + replace。"""
    return str(path.relative_to(source_root)).replace("\\", "/")


def _is_within(source_root: Path, target: Path) -> bool:
    """校验 target 解析后仍在 source_root 内。防 path traversal。"""
    try:
        target_resolved = target.resolve()
        root_resolved = source_root.resolve()
        return target_resolved.is_relative_to(root_resolved)
    except (OSError, ValueError):
        return False


def _search_with_timeout(regex: re.Pattern, line: str) -> re.Match | None:
    """带超时的 regex.search。Linux/Mac 用 SIGALRM,Windows 跳过超时保护。"""
    if sys.platform == "win32" or not hasattr(signal, "SIGALRM"):
        # Windows 无 SIGALRM,直接 search(无 DoS 防护,但 re.error 仍捕获)
        return regex.search(line)

    def _handler(signum, frame):
        raise TimeoutError("regex search timed out")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, _REGEX_TIMEOUT)
    try:
        return regex.search(line)
    except TimeoutError:
        log.warning("regex search timed out after %ss, treating as no match", _REGEX_TIMEOUT)
        return None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


class _BaseTool:
    """工具基类。"""

    name: str = ""

    def schema(self) -> dict:
        raise NotImplementedError

    def run(self, args: dict) -> dict:
        raise NotImplementedError


class ReadFileTool(_BaseTool):
    name = "read_file"

    def __init__(self, source_root: Path, max_bytes: int = 32_000) -> None:
        self.source_root = source_root
        self.max_bytes = max_bytes

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "读取指定源码文件内容。可用 offset/limit 分页读大文件。" "返回文件文本(可能截断)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 repo 根的文件路径,如 'a/b.py'"},
                    "offset": {
                        "type": "integer",
                        "description": "起始行号(1-indexed),默认 1",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "读多少行。不传则读全部(受 32KB 字节闸门);" "传了则按行读,不受字节闸门"
                        ),
                    },
                },
                "required": ["path"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("path", "")
        full = self.source_root / path
        if not _is_within(self.source_root, full):
            return {"content": "", "error": f"path outside repo root: {path}"}
        if not full.exists() or not full.is_file():
            return {"content": "", "error": f"file not found: {path}"}
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total_lines = len(lines)
            offset = max(1, int(args.get("offset", 1)))
            limit_arg = args.get("limit")
            if limit_arg is not None:
                limit = int(limit_arg)
                selected = lines[offset - 1 : offset - 1 + limit]
                content = "\n".join(selected)
                return {
                    "content": content,
                    "offset": offset,
                    "limit": len(selected),
                    "total_lines": total_lines,
                    "truncated": False,
                    "error": None,
                }
            # 没传 limit,走字节闸门
            data = text.encode("utf-8", errors="replace")
            truncated = False
            if len(data) > self.max_bytes:
                data = data[: self.max_bytes]
                truncated = True
            return {
                "content": data.decode("utf-8", errors="replace"),
                "truncated": truncated,
                "total_lines": total_lines,
                "offset": offset,
                "error": None,
            }
        except Exception as e:
            return {"content": "", "error": str(e)}


class GrepTool(_BaseTool):
    name = "grep"

    def __init__(self, source_root: Path, max_matches: int = 200) -> None:
        self.source_root = source_root
        self.max_matches = max_matches

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "在源码里正则搜索。返回命中的 (file, line, text) 列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式"},
                    "scope": {
                        "type": "string",
                        "description": "限定文件路径或 glob,如 'a/*.py';空表示全 repo",
                    },
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        scope = args.get("scope", "")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"matches": [], "truncated": False, "error": f"bad regex: {e}"}

        files: list[Path] = []
        if scope:
            files = list(self.source_root.glob(scope))
            # fallback:如果 glob 无命中且 scope 是 root 内的单文件,按单文件处理
            if not files:
                scope_full = self.source_root / scope
                if _is_within(self.source_root, scope_full) and scope_full.is_file():
                    files = [scope_full]
        else:
            files = [
                f for f in self.source_root.rglob("*") if f.is_file() and ".git" not in f.parts
            ]

        matches: list[dict] = []
        truncated = False
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if len(line) > MAX_LINE_LENGTH:
                    continue  # 跳过超长行(minified/base64),防 DoS
                if _search_with_timeout(regex, line):
                    matches.append(
                        {
                            "file": _rel(self.source_root, f),
                            "line": i,
                            "text": line[:200],
                        }
                    )
                    if len(matches) >= self.max_matches:
                        truncated = True
                        return {"matches": matches, "truncated": truncated, "error": None}
        return {"matches": matches, "truncated": truncated, "error": None}


class GlobTool(_BaseTool):
    name = "glob"

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "按 glob 模式匹配文件路径,返回文件列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式,如 '**/*.py'"},
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"matches": [], "truncated": False, "error": "empty pattern"}
        matched: list[str] = []
        for f in self.source_root.rglob("*"):
            if ".git" in f.parts:
                continue
            rel = _rel(self.source_root, f)
            if fnmatch.fnmatch(rel, pattern):
                matched.append(rel)
                if len(matched) >= MAX_GLOB_RESULTS:
                    return {
                        "matches": sorted(matched),
                        "truncated": True,
                        "note": "Results truncated. Use a more specific pattern.",
                        "error": None,
                    }
        return {"matches": sorted(matched), "truncated": False, "error": None}


class EditTool(_BaseTool):
    name = "Edit"

    def __init__(self, source_root: Path, confirmer) -> None:
        self.source_root = source_root
        self.confirmer = confirmer  # callable(file_path, old, new) -> bool

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "用 old_string 替换 new_string 改文件。old_string 必须唯一。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "相对 cwd 的路径"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("file_path", "")
        full = self.source_root / path
        if not _is_within(self.source_root, full):
            return {"ok": False, "error": "path outside cwd"}
        if not full.exists():
            return {"ok": False, "error": f"file not found: {path}"}
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        content = full.read_text(encoding="utf-8")
        if old not in content:
            return {"ok": False, "error": "old_string not found"}
        if content.count(old) > 1:
            return {"ok": False, "error": "old_string not unique"}
        # 用户确认
        if not self.confirmer(str(full), old, new):
            return {"ok": False, "error": "user denied"}
        new_content = content.replace(old, new, 1)
        full.write_text(new_content, encoding="utf-8")
        return {"ok": True, "path": str(full), "bytes_changed": len(new) - len(old)}


class WriteTool(_BaseTool):
    name = "Write"

    def __init__(self, source_root: Path, confirmer) -> None:
        self.source_root = source_root
        self.confirmer = confirmer

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "创建或覆盖文件。慎用,会覆盖已有内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("file_path", "")
        full = self.source_root / path
        if not _is_within(self.source_root, full):
            return {"ok": False, "error": "path outside cwd"}
        content = args.get("content", "")
        # 用户确认
        if not self.confirmer(str(full), "", content):
            return {"ok": False, "error": "user denied"}
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(full), "bytes": len(content)}


# Bash 命令白名单:前缀匹配。命令必须以下列前缀之一开头(或精确等于去空格后的前缀)。
# 危险命令(rm/dd/mkfs/chmod 777/... )不在列,前缀不匹配即拒。
_BASH_COMMAND_WHITELIST: list[str] = [
    "git ",
    "python ",
    "python3 ",
    "pytest",
    "pip ",
    "ls",
    "cat ",
    "echo ",
    "grep ",
    "find ",
    "ruff",
    "black",
    "pwd",
    "mkdir ",
    "touch ",
]


class BashTool(_BaseTool):
    """执行 shell 命令。命令必须在白名单前缀内,cwd 限定 source_root。

    安全:
    - 命令前缀白名单(前缀匹配),危险命令直接拒
    - cwd 限定在 source_root,Agent 不能在 repo 外面跑
    - subprocess timeout 兜底
    - stdout+stderr 合并输出,内联上限 30000 字符;超长落盘到
      .code-reader/observations/ 并返回 <persisted-output> 包装 + 2KB 预览
    """

    name = "Bash"

    def __init__(self, source_root: Path, timeout: int = 30) -> None:
        self.source_root = source_root
        self.timeout = timeout

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "执行 shell 命令。命令必须在白名单内,且在当前 repo 目录跑。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "shell 命令"},
                },
                "required": ["command"],
            },
        }

    def run(self, args: dict) -> dict:
        command = args.get("command", "").strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        # 白名单检查:任一前缀匹配或精确等于去空格前缀
        if not any(
            command.startswith(prefix) or command == prefix.strip()
            for prefix in _BASH_COMMAND_WHITELIST
        ):
            return {"ok": False, "error": f"command not in whitelist: {command[:50]}"}
        # 跑命令
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.source_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {self.timeout}s"}
        except Exception as e:  # noqa: BLE001 — 兜底,转成 observation
            return {"ok": False, "error": str(e)}
        # stdout + stderr 合并(分别 capture 保留 returncode 关联,截断按合并总长算)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = stdout + ("\n" + stderr if stderr else "")
        output_bytes = len(combined.encode("utf-8"))
        if output_bytes > BASH_MAX_OUTPUT:
            # 落盘完整输出,返回 <persisted-output> 包装 + 2KB 预览
            persist_dir = PathManager.observations_dir(self.source_root)
            persist_id = f"bash-{uuid.uuid4().hex[:8]}"
            persist_file = persist_dir / f"{persist_id}.txt"
            try:
                persist_file.write_text(combined, encoding="utf-8")
            except Exception as e:  # noqa: BLE001 — 落盘失败不致命,fallback 内联截断
                log.warning("bash output persist failed: %s; fallback to inline truncate", e)
                return {
                    "ok": result.returncode == 0,
                    "output": combined[:BASH_MAX_OUTPUT],
                    "returncode": result.returncode,
                }
            preview = combined[:BASH_PREVIEW_BYTES]
            wrapped = (
                f"Output too large ({output_bytes:,} bytes). Full output saved to: "
                f"{persist_file}\n\nPreview (first 2 KB):\n{preview}\n\n[/persisted-output]"
            )
            return {
                "ok": result.returncode == 0,
                "output": wrapped,
                "returncode": result.returncode,
                "persisted_path": str(persist_file),
            }
        return {
            "ok": result.returncode == 0,
            "output": combined,
            "returncode": result.returncode,
        }


class ToolRegistry:
    """工具注册表 + 调度。

    注册 6 个工具:
    read_file / grep / glob / Edit / Write / Bash。

    confirmer 默认 None 时用 AutoDenyConfirmer(拒绝所有改动),防止忘了传
    confirmer 误改文件。测试时显式传 AutoApproveConfirmer / AutoDenyConfirmer。
    """

    def __init__(
        self,
        source_root: Path,
        confirmer=None,
        bash_timeout: int = 30,
    ) -> None:
        if confirmer is None:
            confirmer = AutoDenyConfirmer()
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            EditTool.name: EditTool(source_root, confirmer),
            WriteTool.name: WriteTool(source_root, confirmer),
            BashTool.name: BashTool(source_root, timeout=bash_timeout),
        }

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool: {name}"}
        try:
            return tool.run(args)
        except Exception as e:
            return {"error": f"tool {name} failed: {e}"}
