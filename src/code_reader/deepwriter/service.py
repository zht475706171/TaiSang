"""DeepWriterService:对机制/流程/模块做重点深挖,产 LLM 讲解文本。

依赖:
- render_chain(Task 2)把 symbol_id 列表展成人话叙事
- code_extractor 抽代码片段喂 LLM
"""

from __future__ import annotations

from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from ..types import FlowCandidate, MechanismCandidate, ModuleCandidate, RepoIndex
from .code_extractor import extract_code_snippet
from .prompts import (
    FLOW_SYSTEM,
    FLOW_USER,
    MECHANISM_SYSTEM,
    MECHANISM_USER,
    MODULE_SYSTEM,
    MODULE_USER,
)


def _module_of(file: str) -> str:
    """从 file 路径取顶级模块名。a/b/c.py → a;顶层文件 → ""。"""
    parts = file.split("/")
    return parts[0] if len(parts) > 1 else ""


class DeepWriterService:
    """重点深挖服务:对单个候选写一篇 LLM 讲解。

    使用方注入 LLMClient(线上)或 MockLLM(测试)。
    """

    def __init__(self, llm: LLMClient | MockLLM, source_root: Path) -> None:
        self.llm = llm
        self.source_root = source_root

    def write_mechanism(self, idx: RepoIndex, m: MechanismCandidate) -> str:
        """对单个核心机制候选写讲解。"""
        snippets = self._snippets_for_symbols(idx, [m.symbol_id])
        symbols_text = f"- {m.symbol_id} (in_degree={m.in_degree})"
        prompt = MECHANISM_USER.format(
            name=m.name,
            one_liner=m.one_liner or "(待补)",
            symbols_with_file_line=symbols_text,
            code_snippets=snippets,
        )
        return self._chat(MECHANISM_SYSTEM, prompt)

    def write_flow(self, idx: RepoIndex, f: FlowCandidate) -> str:
        """对单个端到端流程候选写讲解。"""
        snippets = self._snippets_for_symbols(idx, f.chain)
        prompt = FLOW_USER.format(
            name=f.name,
            rendered_chain=f.rendered,
            code_snippets=snippets,
        )
        return self._chat(FLOW_SYSTEM, prompt)

    def write_module(self, idx: RepoIndex, m: ModuleCandidate) -> str:
        """对单个核心模块候选写讲解。"""
        mod_symbols = [s for s in idx.symbols if _module_of(s.file) == m.path]
        syms_text = "\n".join(f"- {s.id}" for s in mod_symbols[:20])
        prompt = MODULE_USER.format(
            module_path=m.path or "(root)",
            file_count=m.file_count,
            one_liner=m.one_liner or "(待补)",
            symbols=syms_text,
        )
        return self._chat(MODULE_SYSTEM, prompt)

    def _snippets_for_symbols(self, idx: RepoIndex, symbol_ids: list[str]) -> str:
        """根据 symbol_id 列表抽所有可定位的代码片段,拼成一段文本。"""
        by_id = {s.id: s for s in idx.symbols}
        parts: list[str] = []
        for sid in symbol_ids:
            s = by_id.get(sid)
            if not s:
                continue
            f = self.source_root / s.file
            if not f.exists():
                continue
            parts.append(extract_code_snippet(f, s.file, s.line_range[0], s.line_range[1]))
        return "\n\n".join(parts)

    def _chat(self, system: str, user: str) -> str:
        """发一次 chat,返回 text。"""
        resp = self.llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[],
        )
        return resp.text
