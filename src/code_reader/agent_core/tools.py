"""Agent 5 工具实现。

每个工具:
- schema(): 返回 OpenAI function schema
- run(args): 执行,返回 dict observation

工具集:
- read_file(path) — 读文件
- grep(pattern, scope) — 正则搜
- glob(pattern) — 文件名匹配
- trace_call_chain(symbol_id, depth) — 调用链追踪
- lookup_map(layer, query) — 查 RepoMap

安全:
- ReadFileTool/GrepTool 对 path/scope 做 containment 校验,拒绝越界访问
- GrepTool 的 regex.search 有超时保护(Linux/Mac via signal.SIGALRM,Windows 跳过)
"""

from __future__ import annotations

import fnmatch
import logging
import re
import signal
import sys
from pathlib import Path

from ..indexer.linker import CallGraphNode, resolve_call_chain
from ..types import RepoMap

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


class LookupMapTool(_BaseTool):
    name = "lookup_map"

    def __init__(self, repo_map: RepoMap) -> None:
        self.repo_map = repo_map

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "查代码库地图(分层摘要)。layer: 'global' / 'module' / 'file'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": ["global", "module", "file"]},
                    "query": {"type": "string", "description": "过滤关键词(可空)"},
                },
                "required": ["layer"],
            },
        }

    def run(self, args: dict) -> dict:
        layer = args.get("layer", "")
        query = args.get("query", "").lower()
        if layer == "global":
            g = self.repo_map.global_summary
            text = (
                f"入口: {', '.join(g.entry_points)}\n"
                f"核心模块: {', '.join(g.core_modules)}\n"
                f"摘要: {g.dependency_summary}"
            )
            return {"text": text, "error": None}
        if layer == "module":
            lines = []
            for mp, ms in self.repo_map.module_summaries.items():
                if not query or query in ms.summary.lower() or query in mp.lower():
                    lines.append(f"[{mp or '(root)'}] {ms.file_count} 文件: {ms.summary}")
            return {"text": "\n".join(lines), "error": None}
        if layer == "file":
            lines = []
            for fp, fs in self.repo_map.file_summaries.items():
                if not query or query in fs.summary.lower() or query in fp.lower():
                    lines.append(f"[{fp}] {fs.summary}")
            return {"text": "\n".join(lines), "error": None}
        return {"text": "", "error": f"unknown layer: {layer}"}


class WriteDocTool(_BaseTool):
    """把一个章节写到 markdown 文件。

    section_path 相对 doc_dir,落盘前做 containment 校验防 path traversal。
    文件名(去扩展名)自动作为 # 一级标题,内容追加其后。
    """

    name = "write_doc"

    def __init__(self, doc_dir: Path) -> None:
        self.doc_dir = doc_dir

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "把一个章节写到 markdown 文件。section_path 是相对 doc_dir 的路径,"
                "如 '02_核心机制/01_依赖注入.md'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_path": {"type": "string", "description": "相对 doc_dir 的路径"},
                    "content": {"type": "string", "description": "章节 markdown 内容"},
                },
                "required": ["section_path", "content"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("section_path", "")
        content = args.get("content", "")
        if not path:
            return {"ok": False, "error": "empty section_path"}
        full = self.doc_dir / path
        if not _is_within(self.doc_dir, full):
            return {"ok": False, "error": "path outside doc dir"}
        full.parent.mkdir(parents=True, exist_ok=True)
        # 文件名(去扩展名)作为一级标题
        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        full.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        return {"ok": True, "path": str(full)}


class ListPendingSectionsTool(_BaseTool):
    """列出还没写的章节。

    判定规则:
    - 占位文件不存在 → pending
    - 内容含 "(待填" → pending
    - 内容长度 < 50 字符 → pending
    """

    name = "list_pending_sections"

    def __init__(self, doc_dir: Path, all_sections: list[str]) -> None:
        self.doc_dir = doc_dir
        self.all_sections = all_sections

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "列出还没写的章节(占位文件不存在或为空的章节)。",
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, args: dict) -> dict:
        pending: list[str] = []
        for s in self.all_sections:
            full = self.doc_dir / s
            if not full.exists():
                pending.append(s)
                continue
            content = full.read_text(encoding="utf-8", errors="replace")
            if "(待填" in content or len(content) < 50:
                pending.append(s)
        return {"pending": pending, "total": len(self.all_sections)}


class FinalizeDocTool(_BaseTool):
    """文档写完的收尾信号工具。

    AgentService 检测到本工具被调用即结束 run,返回 "文档生成完成"。
    本工具不实际生成 REPO_GUIDE.md(由 DocGenService 在更上层负责),
    只返回 ok 信号给 agent loop 当作普通 observation。
    """

    name = "finalize_doc"

    def __init__(self, doc_dir: Path) -> None:
        self.doc_dir = doc_dir

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "全部章节写完后调用,生成 REPO_GUIDE.md 总览并结束任务。",
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, args: dict) -> dict:
        return {"ok": True, "message": "finalize signal"}


class ToolRegistry:
    """工具注册表 + 调度。

    doc_dir / all_sections 都给齐时,额外注册 WriteDoc / ListPendingSections / FinalizeDoc;
    否则只注册老 5 个工具(向后兼容 Task 1-11 测试)。
    """

    def __init__(
        self,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        doc_dir: Path | None = None,
        all_sections: list[str] | None = None,
    ) -> None:
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            TraceCallChainTool.name: TraceCallChainTool(call_graph),
            LookupMapTool.name: LookupMapTool(repo_map),
        }
        if doc_dir is not None:
            self._tools[WriteDocTool.name] = WriteDocTool(doc_dir)
        if doc_dir is not None and all_sections is not None:
            self._tools[ListPendingSectionsTool.name] = ListPendingSectionsTool(
                doc_dir, all_sections
            )
            self._tools[FinalizeDocTool.name] = FinalizeDocTool(doc_dir)

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
