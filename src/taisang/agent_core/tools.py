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
- Bash(command) — 执行 shell 命令(持久 shell,cd 持久化,危险命令黑名单)

安全:
- 文件工具对 path 做 PermissionManager.check():首次访问新目录问用户批准,
  批准后该目录(项目根)加入已批准集合,后续不再问。类似 Claude Code permission。
- 文件工具接受绝对路径或相对 cwd 的路径(cwd 随 Bash cd 动态同步)
- BashTool 的 cd 切到未批准目录时也先问用户;批准后后续文件工具跟过去不问
- EditTool/WriteTool 改文件前调用 confirmer,默认 AutoDenyConfirmer(拒绝所有)
- GrepTool 的 regex.search 有超时保护(Linux/Mac via signal.SIGALRM,Windows 跳过)
- BashTool 用持久 shell(claude code 风格),cd 持久化,危险命令黑名单,输出截断保护
"""

from __future__ import annotations

import fnmatch
import logging
import re
import signal
import sys
import uuid
from pathlib import Path

from ..storage.paths import PathManager
from .confirm import AutoDenyConfirmer
from .permission import AutoApprovePermissionManager, PermissionManager

log = logging.getLogger(__name__)

# regex search 超时秒数(仅 Linux/Mac 生效,Windows 跳过)
_REGEX_TIMEOUT = 5.0

# Bash 合并输出内联上限(对齐 Claude Code BashTool)。超长落盘到 .taisang/observations/。
BASH_MAX_OUTPUT = 30_000
# 落盘时给 agent 的预览字节数。
BASH_PREVIEW_BYTES = 2000

# Glob 硬切上限(对齐 Claude Code GlobTool)。
MAX_GLOB_RESULTS = 100

# Grep 跳过超长行(对齐 Claude Code --max-columns,防 minified/base64 行 DoS)。
MAX_LINE_LENGTH = 500


def _rel(cwd: Path, path: Path) -> str:
    """返回相对 cwd 的 Unix 风格路径。消除重复的 relative_to + replace。"""
    return str(path.relative_to(cwd)).replace("\\", "/")


def _resolve_path(path: str, cwd: Path) -> Path:
    """解析路径:绝对路径直接用,相对路径拼 cwd。"""
    p = Path(path)
    if p.is_absolute():
        return p
    return cwd / p


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
    # 单条 observation 持久化阈值(字符数)。对齐 claude-code maxResultSizeChars。
    # - 默认 100_000:小结果工具(Edit/Write/Todo/Glob)
    # - Infinity:ReadFileTool(opt-out 永不持久化,读回文件是循环)
    # - 30_000:BashTool(自己已落盘,enforce_budget 见到的是包装结果)
    # - 20_000:GrepTool(对齐 claude-code GrepTool)
    max_result_size_chars: float = 100_000

    def schema(self) -> dict:
        raise NotImplementedError

    def run(self, args: dict) -> dict:
        raise NotImplementedError


class ReadFileTool(_BaseTool):
    name = "read_file"
    # Infinity:opt-out 持久化。Read 自管 256KB 抛错 + 按行读,
    # 持久化 Read 结果到文件再被 LLM 读回是循环,永不持久化。
    # 对齐 claude-code FileReadTool.ts:342 maxResultSizeChars: Infinity。
    max_result_size_chars = float("inf")

    def __init__(self, cwd: Path, permission: PermissionManager, max_bytes: int = 32_000) -> None:
        self.cwd = cwd
        self.permission = permission
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
                    "path": {
                        "type": "string",
                        "description": "文件路径,相对 cwd 或绝对路径,如 'a/b.py' 或 '/abs/path'",
                    },
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
        full = _resolve_path(path, self.cwd)
        if not self.permission.check(full):
            return {"content": "", "error": f"permission denied: {path}"}
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
    # 对齐 claude-code GrepTool maxResultSizeChars=20_000。
    max_result_size_chars = 20_000

    def __init__(self, cwd: Path, permission: PermissionManager, max_matches: int = 200) -> None:
        self.cwd = cwd
        self.permission = permission
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
                        "description": "限定 cwd 下文件路径或 glob,如 'a/*.py';空表示全 cwd",
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
            scope_full = _resolve_path(scope, self.cwd)
            # scope 是 glob:用 parent.glob(name),支持相对/绝对
            if any(ch in scope for ch in "*?["):
                parent = scope_full.parent
                name = scope_full.name
                # glob 模式:对 parent 目录做权限检查
                if not self.permission.check(parent):
                    return {
                        "matches": [],
                        "truncated": False,
                        "error": f"permission denied: {scope}",
                    }
                files = list(parent.glob(name))
            elif scope_full.is_file():
                if not self.permission.check(scope_full):
                    return {
                        "matches": [],
                        "truncated": False,
                        "error": f"permission denied: {scope}",
                    }
                files = [scope_full]
            else:
                files = []
        else:
            if not self.permission.check(self.cwd):
                return {
                    "matches": [],
                    "truncated": False,
                    "error": "permission denied: cwd not approved",
                }
            files = [f for f in self.cwd.rglob("*") if f.is_file() and ".git" not in f.parts]

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
                            "file": str(f).replace("\\", "/"),
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
    max_result_size_chars = 100_000

    def __init__(self, cwd: Path, permission: PermissionManager) -> None:
        self.cwd = cwd
        self.permission = permission

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "按 glob 模式匹配文件路径,返回文件列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "glob 模式,相对 cwd 或绝对路径,如 '**/*.py'",
                    },
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"matches": [], "truncated": False, "error": "empty pattern"}
        # pattern 是绝对路径:从该目录 rglob;相对:从 cwd rglob
        pat_path = Path(pattern)
        if pat_path.is_absolute():
            root = pat_path
            rel_base = pat_path
        else:
            root = self.cwd
            rel_base = self.cwd
        if not self.permission.check(root):
            return {"matches": [], "truncated": False, "error": "permission denied"}
        matched: list[str] = []
        for f in root.rglob("*"):
            if ".git" in f.parts:
                continue
            rel = _rel(rel_base, f)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(str(f).replace("\\", "/"), pattern):
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
    max_result_size_chars = 100_000

    def __init__(self, cwd: Path, permission: PermissionManager, confirmer) -> None:
        self.cwd = cwd
        self.permission = permission
        self.confirmer = confirmer  # callable(file_path, old, new) -> bool

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "用 old_string 替换 new_string 改文件。old_string 必须唯一。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径,相对 cwd 或绝对路径",
                    },
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("file_path", "")
        full = _resolve_path(path, self.cwd)
        if not self.permission.check(full):
            return {"ok": False, "error": "permission denied"}
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
    max_result_size_chars = 100_000

    def __init__(self, cwd: Path, permission: PermissionManager, confirmer) -> None:
        self.cwd = cwd
        self.permission = permission
        self.confirmer = confirmer

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "创建或覆盖文件。慎用,会覆盖已有内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径,相对 cwd 或绝对路径",
                    },
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("file_path", "")
        full = _resolve_path(path, self.cwd)
        if not self.permission.check(full):
            return {"ok": False, "error": "permission denied"}
        content = args.get("content", "")
        # 用户确认
        if not self.confirmer(str(full), "", content):
            return {"ok": False, "error": "user denied"}
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(full), "bytes": len(content)}


# Bash 危险命令黑名单:出现这些模式直接拒。允许 cd / git / python / ls 等常用命令。
# 黑名单而非白名单:Claude Code 风格,允许动态切目录 + 任意非危险命令。
_BASH_DANGEROUS_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf *",
    "mkfs",
    "dd if=",
    ":(){",  # fork bomb
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "halt",
    "kill -9 1",
    "git push --force",  # 强推 main 危险
    "git push -f origin main",
    "> /dev/sda",
    "curl.*|.*sh",  # 远程脚本执行
    "wget.*|.*sh",
]


def _is_dangerous(command: str) -> bool:
    """检查命令是否匹配危险模式。"""
    import re as _re

    cmd_lower = command.lower()
    for pat in _BASH_DANGEROUS_PATTERNS:
        if _re.search(pat, cmd_lower):
            return True
    return False


class BashTool(_BaseTool):
    """执行 shell 命令,用持久 shell(claude code 风格)。

    安全:
    - 危险命令黑名单(rm -rf / / mkfs / fork bomb / 强推 main 等)
    - cd 持久化:持久 shell 内 cd 改 cwd,后续命令沿用(类 Claude Code)
    - cd 到新目录前问用户批准(PermissionManager.check)
    - 超时兜底(PipeShell 内部实现)
    - stdout+stderr 合并输出,内联上限 30000 字符;超长落盘到
      .taisang/observations/ 并返回 <persisted-output> 包装 + 2KB 预览

    路径:不再限定 source_root。cd 可切到任意目录,首次切到新目录问用户;
    批准后该目录(项目根)加入已批准集合,后续不再问。
    """

    name = "Bash"
    # 30_000:BashTool 自己已落盘超长输出到 .taisang/observations/,
    # enforce_budget 见到的是 < 30KB 的 <persisted-output> 包装结果,不会重复持久化。
    # 对齐 claude-code BashTool maxResultSizeChars=30_000。
    max_result_size_chars = 30_000

    def __init__(
        self,
        shell,
        observations_dir: Path,
        permission: PermissionManager | None = None,
        timeout: int = 30,
    ) -> None:
        """
        shell: PersistentShell 实例(由 AgentService 持有,跨 Bash 调用复用)。
        observations_dir: 超长输出落盘目录。
        permission: PermissionManager,cd 切新目录前问用户批准。None 时用
            AutoApprovePermissionManager(测试场景,无脑批准)。
        """
        self.shell = shell
        self.observations_dir = observations_dir
        self.permission = permission or AutoApprovePermissionManager(
            initial_dirs=[shell.cwd()] if shell is not None else []
        )
        self.timeout = timeout

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "执行 shell 命令。用持久 shell,cd 改的 cwd 跨调用保留。"
                "cd 切到新目录首次会问用户批准。"
                "危险命令(rm -rf / / mkfs / 强推 main)会被拒。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "shell 命令"},
                },
                "required": ["command"],
            },
        }

    def run(self, args: dict, cancel_event=None) -> dict:
        command = args.get("command", "").strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        # 危险命令黑名单检查
        if _is_dangerous(command):
            return {"ok": False, "error": f"dangerous command blocked: {command[:80]}"}
        # cd 命令:先问用户权限,批准再交给 shell 执行
        import re as _re

        cd_match = _re.match(r"^\s*cd\s+(?P<path>[^\s;&|]+|\"[^\"]+\"|'[^']+')\s*$", command)
        if cd_match:
            raw_path = cd_match.group("path").strip("'\"")
            target = Path(raw_path)
            if not target.is_absolute():
                target = self.shell.cwd() / target
            try:
                target_resolved = target.resolve()
            except (OSError, ValueError) as e:
                return {"ok": False, "error": f"cd: {e}"}
            if not self.permission.check(target_resolved):
                return {"ok": False, "error": f"permission denied: {raw_path}"}
        # 跑命令(持久 shell,支持 cancel_event 中断)
        try:
            result = self.shell.run(command, timeout=self.timeout, cancel_event=cancel_event)
        except Exception as e:  # noqa: BLE001 — 兜底,转成 observation
            return {"ok": False, "error": str(e)}
        # 中断:抛 InterruptedError,让 ToolRegistry.call 透传给主循环
        if result.get("interrupted"):
            raise InterruptedError("bash command interrupted by user")
        combined = result.get("output", "")
        ok = result.get("ok", False)
        returncode = result.get("returncode")
        # 超时特殊标记
        if result.get("timeout"):
            return {"ok": False, "error": f"timeout after {self.timeout}s", "output": combined}
        output_bytes = len(combined.encode("utf-8"))
        if output_bytes > BASH_MAX_OUTPUT:
            # 落盘完整输出,返回 <persisted-output> 包装 + 2KB 预览
            persist_dir = self.observations_dir
            persist_id = f"bash-{uuid.uuid4().hex[:8]}"
            persist_file = persist_dir / f"{persist_id}.txt"
            try:
                persist_file.write_text(combined, encoding="utf-8")
            except Exception as e:  # noqa: BLE001 — 落盘失败不致命,fallback 内联截断
                log.warning("bash output persist failed: %s; fallback to inline truncate", e)
                return {
                    "ok": ok,
                    "output": combined[:BASH_MAX_OUTPUT],
                    "returncode": returncode,
                }
            preview = combined[:BASH_PREVIEW_BYTES]
            wrapped = (
                f"Output too large ({output_bytes:,} bytes). Full output saved to: "
                f"{persist_file}\n\nPreview (first 2 KB):\n{preview}\n\n[/persisted-output]"
            )
            return {
                "ok": ok,
                "output": wrapped,
                "returncode": returncode,
                "persisted_path": str(persist_file),
            }
        return {
            "ok": ok,
            "output": combined,
            "returncode": returncode,
        }


class TodoWriteTool(_BaseTool):
    """任务追踪工具。LLM 主动调用,把任务拆成显式 todo 列表。

    覆盖式更新:每次调用传全量 todos(不是增量)。LLM 负责维护完整状态。
    observation 自然落盘 jsonl(走 ToolRegistry.call 标准路径),
    resume 时从最后一条 TodoWrite tool_call 重建。

    service 引用:调 service.todos = new_todos + service._emit_todo_update()。
    子 agent 的 ToolRegistry 也注册(传 child_service),emit 带 agent_id 嵌套到父卡片。
    """

    name = "TodoWrite"

    def __init__(self, service) -> None:
        self._service = service

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "任务追踪工具。复杂任务(3+ 步)用这个把任务拆成显式 todo 列表,"
                "执行中随时更新状态。用户能看到当前进度、剩余步骤。"
                "每次调用传全量 todos(覆盖式更新,不是增量)。"
                "简单任务(单步读文件回答)不需要调。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "全量 todo 列表(覆盖现有)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "任务描述(简短,祈使句)",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": (
                                        "pending=未开始,in_progress=进行中(同时只 1 个),"
                                        "completed=已完成"
                                    ),
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "进行中显示的动名词形式(如 '正在读文件'),可选",
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        }

    def run(self, args: dict) -> dict:
        todos = args.get("todos", [])
        if not isinstance(todos, list):
            return {"error": "todos must be array"}
        validated: list[dict] = []
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return {"error": f"todo[{i}] must be object"}
            content = t.get("content", "")
            status = t.get("status", "pending")
            if not content or not isinstance(content, str):
                return {"error": f"todo[{i}].content required"}
            if status not in ("pending", "in_progress", "completed"):
                return {"error": f"todo[{i}].status invalid: {status}"}
            validated.append(
                {
                    "content": content,
                    "status": status,
                    "activeForm": t.get("activeForm", "") or "",
                }
            )
        # 覆盖式更新 service.todos + emit TODO_UPDATE 事件
        self._service.todos = validated
        self._service._emit_todo_update(validated)
        return {"ok": True, "todos": validated, "count": len(validated)}


class ToolRegistry:
    """工具注册表 + 调度。

    注册 6 个工具:
    read_file / grep / glob / Edit / Write / Bash。

    动态 cwd:Bash cd 改的是 shell 内部 cwd,文件工具(Read/Grep/Glob/Edit/Write)
    需要跟随。每次 call() 前从 shell.cwd() 同步到文件工具的 cwd 属性,保证文件
    工具解析相对路径时用 shell 当前 cwd。

    permission: PermissionManager,首次访问新目录问用户批准。默认 None 时用
    AutoApprovePermissionManager(测试用,无脑批准)。生产场景 CLI 传 CliPermissionManager,
    Web 传 WebPermissionManager。

    confirmer 默认 None 时用 AutoDenyConfirmer(拒绝所有改动),防止忘了传
    confirmer 误改文件。测试时显式传 AutoApproveConfirmer / AutoDenyConfirmer。
    """

    def __init__(
        self,
        cwd: Path,
        shell=None,
        confirmer=None,
        permission: PermissionManager | None = None,
        bash_timeout: int = 30,
        observations_dir: Path | None = None,
        skills: list | None = None,
        ctx=None,
        mcp_manager=None,
        agents: list | None = None,
        parent_service=None,
        cancel_event=None,
        service=None,
    ) -> None:
        if confirmer is None:
            confirmer = AutoDenyConfirmer()
        if permission is None:
            permission = AutoApprovePermissionManager(initial_dirs=[cwd])
        if observations_dir is None:
            observations_dir = PathManager.observations_dir(cwd)
        self._shell = shell
        self._permission = permission
        self._cwd = cwd
        self._bash_timeout = bash_timeout
        # 文件工具:用 cwd + permission
        self._read = ReadFileTool(cwd, permission)
        self._grep = GrepTool(cwd, permission)
        self._glob = GlobTool(cwd, permission)
        self._edit = EditTool(cwd, permission, confirmer)
        self._write = WriteTool(cwd, permission, confirmer)
        self._bash: BashTool | None = None
        if shell is not None:
            self._bash = BashTool(
                shell, observations_dir, permission=permission, timeout=bash_timeout
            )
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: self._read,
            GrepTool.name: self._grep,
            GlobTool.name: self._glob,
            EditTool.name: self._edit,
            WriteTool.name: self._write,
        }
        if self._bash is not None:
            self._tools[BashTool.name] = self._bash
        # SkillTool:LLM 调用 skill 工具,把 SKILL.md 正文注入 ctx。
        # 局部导入避免循环引用(skill_tool.py 从 tools.py 导入 _BaseTool)。
        if skills:
            from .skill_tool import SkillTool
            self._tools[SkillTool.name] = SkillTool(skills=skills, ctx=ctx)
        # MCP 工具:动态注册(仅在传入 mcp_manager 时)。
        # 局部导入避免循环引用(mcp.tool 从 tools.py 导入 _BaseTool)。
        if mcp_manager:
            from ..mcp.tool import McpPromptTool, McpResourceTool, MCPTool
            for mcp_tool in mcp_manager.get_all_mcp_tools():
                self._tools[mcp_tool["name"]] = MCPTool(
                    server_name=mcp_tool["server"],
                    tool_info=mcp_tool["tool_info"],
                    manager=mcp_manager,
                )
            # 伪工具:读取 MCP 资源 / 获取 MCP prompt(无连接 server 时调用会返回错误)
            self._tools["mcp_resource"] = McpResourceTool(mcp_manager)
            self._tools["mcp_prompt"] = McpPromptTool(mcp_manager)
        # AgentTool:LLM 调用派子 agent。仅当传入 agents + parent_service 时注册
        # (子 agent 的 ToolRegistry 不传 agents,物理防递归)。
        # 局部导入避免循环引用(agent_tool.py 从 tools.py 导入 _BaseTool)。
        self._parent_service = parent_service
        if agents and parent_service is not None:
            from .agent_tool import AgentTool
            self._tools[AgentTool.name] = AgentTool(
                agents=agents,
                parent_service=parent_service,
                source_root=cwd,
                confirmer=confirmer,
                mcp_manager=mcp_manager,
            )
        # 用户中断信号:工具执行前检查,set 时抛 InterruptedError。
        # 默认 None(向后兼容,现有调用不受影响)。
        self._cancel_event = cancel_event
        # TodoWriteTool:LLM 主动调用的任务追踪工具。所有 agent 都注册(主 + 子)。
        # service 引用:用于存 todos + emit TODO_UPDATE 事件。
        if service is not None:
            self._tools[TodoWriteTool.name] = TodoWriteTool(service=service)
            # UpdateProfileTool:LLM 发现用户偏好时调,更新画像某一栏。
            # service 引用:用于 emit PROFILE_UPDATE 事件(前端 toast)。
            # agent_id 用 getattr 兜底(测试 FakeService 可能没此属性)。
            from ..user_profile.tool import UpdateProfileTool
            self._tools[UpdateProfileTool.name] = UpdateProfileTool(
                session_id=getattr(service, "agent_id", ""),
                parent_service=service,
            )

    def _sync_cwd(self) -> None:
        """从 shell 拿当前 cwd,同步到所有文件工具。Bash cd 后文件工具跟随。"""
        if self._shell is not None:
            self._cwd = self._shell.cwd()
        self._read.cwd = self._cwd
        self._grep.cwd = self._cwd
        self._glob.cwd = self._cwd
        self._edit.cwd = self._cwd
        self._write.cwd = self._cwd

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def flush_skill_injections(self) -> None:
        """触发 SkillTool 的 pending 注入(若有注册)。

        AgentService 在本轮全部 tool_result append 完之后调用,保证
        SKILL.md 的 user 注入排在 tool 消息之后,符合 OpenAI 协议。
        """
        tool = self._tools.get("skill")
        if tool is not None:
            tool.flush()

    def flush_async_notifications(self) -> None:
        """触发 parent_service 的 async 通知 flush(若有 parent_service)。

        AgentService 主循环在本轮 tool_result 后调用,跟 flush_skill_injections 同位置。
        """
        if self._parent_service is not None:
            self._parent_service.flush_async_notifications()

    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool: {name}"}
        # 用户中断检查:执行前检查 cancel_event,set 时抛 InterruptedError。
        # AgentService 主循环 catch 后走中断分支(补空 tool_result + [interrupted] 标记)。
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise InterruptedError("tool execution cancelled by user")
        # 每次调用前同步 cwd(Bash cd 后文件工具跟随)
        self._sync_cwd()
        try:
            # 透传 cancel_event 给支持的工具(目前只有 BashTool)。
            # 用 inspect 检查 run 签名是否接受 cancel_event 参数,兼容旧工具。
            import inspect as _inspect
            sig = _inspect.signature(tool.run)
            if "cancel_event" in sig.parameters:
                return tool.run(args, cancel_event=self._cancel_event)
            return tool.run(args)
        except InterruptedError:
            raise  # 透传,主循环 catch 走中断分支
        except Exception as e:
            return {"error": f"tool {name} failed: {e}"}
