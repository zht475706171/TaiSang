"""Agent 工具实现。

每个工具:
- schema(): 返回 OpenAI function schema
- run(args): 执行,返回 dict observation

工具集(ToolRegistry 注册 7 个工具):
- read_file(path) — 读文件
- grep(pattern, scope) — 正则搜
- glob(pattern) — 文件名匹配
- trace_call_chain(symbol_id, depth) — 调用链追踪
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
from pathlib import Path

from ..indexer.linker import CallGraphNode, resolve_call_chain
from .confirm import AutoDenyConfirmer

log = logging.getLogger(__name__)

# regex search 超时秒数(仅 Linux/Mac 生效,Windows 跳过)
_REGEX_TIMEOUT = 5.0


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
            "description": "读取指定源码文件内容。返回文件文本(可能截断)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 repo 根的文件路径,如 'a/b.py'"},
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
            data = full.read_bytes()
            truncated = False
            if len(data) > self.max_bytes:
                data = data[: self.max_bytes]
                truncated = True
            return {
                "content": data.decode("utf-8", errors="replace"),
                "truncated": truncated,
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
            return {"matches": [], "error": "empty pattern"}
        matched: list[str] = []
        for f in self.source_root.rglob("*"):
            if ".git" in f.parts:
                continue
            rel = _rel(self.source_root, f)
            if fnmatch.fnmatch(rel, pattern):
                matched.append(rel)
        return {"matches": sorted(matched), "error": None}


class TraceCallChainTool(_BaseTool):
    name = "trace_call_chain"

    def __init__(self, call_graph: dict[str, CallGraphNode]) -> None:
        self.call_graph = call_graph

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "从某符号出发,追踪 N 跳调用链。返回 symbol_id 列表(含起点)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_id": {
                        "type": "string",
                        "description": "起点符号 id,格式 'file::Class.method' 或 'file::func'",
                    },
                    "depth": {"type": "integer", "description": "追踪深度,默认 3", "default": 3},
                },
                "required": ["symbol_id"],
            },
        }

    def run(self, args: dict) -> dict:
        sid = args.get("symbol_id", "")
        depth = int(args.get("depth", 3))
        if not sid:
            return {"chain": [], "error": "empty symbol_id"}
        if sid not in self.call_graph:
            return {"chain": [], "error": f"symbol not in call graph: {sid}"}
        chain = resolve_call_chain(self.call_graph, sid, depth=depth)
        return {"chain": chain, "error": None}


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
    - stdout 截断 5000 字符、stderr 截断 2000 字符,防 context 撑爆
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
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout[:5000],  # 截断保护
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {self.timeout}s"}
        except Exception as e:  # noqa: BLE001 — 兜底,转成 observation
            return {"ok": False, "error": str(e)}


class ToolRegistry:
    """工具注册表 + 调度。

    注册 7 个工具:
    read_file / grep / glob / trace_call_chain / Edit / Write / Bash。

    confirmer 默认 None 时用 AutoDenyConfirmer(拒绝所有改动),防止忘了传
    confirmer 误改文件。测试时显式传 AutoApproveConfirmer / AutoDenyConfirmer。
    """

    def __init__(
        self,
        source_root: Path,
        call_graph: dict[str, CallGraphNode] | None = None,
        confirmer=None,
        bash_timeout: int = 30,
    ) -> None:
        if confirmer is None:
            confirmer = AutoDenyConfirmer()
        if call_graph is None:
            call_graph = {}
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            TraceCallChainTool.name: TraceCallChainTool(call_graph),
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
