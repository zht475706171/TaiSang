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
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ..indexer.linker import CallGraphNode, resolve_call_chain
from ..types import RepoMap


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
            if not files and (self.source_root / scope).is_file():
                files = [self.source_root / scope]
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
                if regex.search(line):
                    matches.append(
                        {
                            "file": str(f.relative_to(self.source_root)).replace("\\", "/"),
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
            rel = str(f.relative_to(self.source_root)).replace("\\", "/")
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


class ToolRegistry:
    """工具注册表 + 调度。"""

    def __init__(
        self,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
    ) -> None:
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            TraceCallChainTool.name: TraceCallChainTool(call_graph),
            LookupMapTool.name: LookupMapTool(repo_map),
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
