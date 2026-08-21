"""分层摘要服务:文件级 → 模块级 → 全局级。

LLM 失败时跳过该文件,记录到 errors,不崩。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from ..types import FileSummary, GlobalSummary, ModuleSummary, RepoIndex, RepoMap
from .prompts import (
    FILE_SUMMARY_SYSTEM,
    GLOBAL_SUMMARY_SYSTEM,
    MODULE_SUMMARY_SYSTEM,
    build_file_summary_prompt,
    build_global_summary_prompt,
    build_module_summary_prompt,
)

log = logging.getLogger(__name__)

# 简单 token 预算控制:超过这个字数就再压一层(简化版,不做真 token 计数)
FILE_BUDGET = 200  # 字数
MODULE_BUDGET = 600
GLOBAL_BUDGET = 2000


class SummarizerService:
    """三层摘要服务。"""

    def __init__(self, llm: LLMClient | MockLLM) -> None:
        self.llm = llm
        self.errors: list[dict] = []

    def _chat(self, system: str, user: str) -> str | None:
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                tools=[],
            )
            text = resp.text.strip()
            if not text:
                return None
            # 字数预算控制(超了截断,简化版)
            return text
        except Exception as e:
            log.warning("LLM chat failed: %s", e)
            return None

    def summarize(self, idx: RepoIndex, source_root: Path) -> RepoMap:
        """产三层 RepoMap。"""
        self.errors = []

        # 文件级
        file_summaries: dict[str, FileSummary] = {}
        # 按文件分组 symbols
        by_file: dict[str, list] = {}
        for s in idx.symbols:
            by_file.setdefault(s.file, []).append(s)

        for rel_path in idx.files:
            src_file = source_root / rel_path
            if not src_file.exists():
                self.errors.append(
                    {"file": rel_path, "stage": "summarize", "error": "source not found"}
                )
                continue
            try:
                source = src_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                self.errors.append({"file": rel_path, "stage": "summarize", "error": str(e)})
                continue
            syms = by_file.get(rel_path, [])
            prompt = build_file_summary_prompt(rel_path, source, syms)
            summary = self._chat(FILE_SUMMARY_SYSTEM, prompt)
            if summary is None:
                self.errors.append(
                    {"file": rel_path, "stage": "summarize", "error": "LLM returned empty"}
                )
                continue
            file_summaries[rel_path] = FileSummary(
                file=rel_path,
                summary=summary[:FILE_BUDGET],
                symbol_ids=[s.id for s in syms],
            )

        # 模块级:按目录分组
        modules: dict[str, list[tuple[str, str]]] = {}
        for fp, fs in file_summaries.items():
            dir_path = str(Path(fp).parent).replace("\\", "/")
            if dir_path == ".":
                dir_path = ""
            modules.setdefault(dir_path, []).append((fp, fs.summary))

        module_summaries: dict[str, ModuleSummary] = {}
        for mp, files in modules.items():
            prompt = build_module_summary_prompt(mp, files)
            summary = self._chat(MODULE_SUMMARY_SYSTEM, prompt)
            if summary is None:
                continue
            module_summaries[mp] = ModuleSummary(
                path=mp,
                summary=summary[:MODULE_BUDGET],
                file_count=len(files),
            )

        # 全局级:入口候选(用符号名,便于识别 main/__main__/run/app 等常见入口名)
        entry_candidates = [
            s.name
            for s in idx.symbols
            if s.name in {"main", "__main__", "run", "app", "create_app", "start"}
        ]
        prompt = build_global_summary_prompt(
            [(mp, ms.summary) for mp, ms in module_summaries.items()],
            entry_candidates,
        )
        global_text = self._chat(GLOBAL_SUMMARY_SYSTEM, prompt) or ""
        global_summary = GlobalSummary(
            entry_points=entry_candidates[:10],
            core_modules=list(module_summaries.keys())[:10],
            dependency_summary=global_text[:GLOBAL_BUDGET],
        )

        return RepoMap(
            global_summary=global_summary,
            module_summaries=module_summaries,
            file_summaries=file_summaries,
        )
