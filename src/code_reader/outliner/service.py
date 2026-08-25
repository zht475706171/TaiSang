"""OutlinerService:编排入口/机制/流程/模块四类候选的挖掘。

selector(LLM 选 5-10 个核心机制)是 Task 5 的事,本模块暂时跳过,
selected_mechanisms 直接给空列表,等 Task 5 接入。
"""

from __future__ import annotations

from ..llm_client import LLMClient, MockLLM
from ..types import Outline, RepoIndex
from .entry_points import find_entry_points
from .flow_candidates import find_flow_candidates
from .mechanism_candidates import find_mechanism_candidates
from .module_candidates import find_module_candidates

# Task 5 接入 selector 后启用
# from .selector import select_mechanisms


class OutlinerService:
    """编排 outliner 四类候选挖掘,产出 Outline。"""

    def __init__(self, llm: LLMClient | MockLLM) -> None:
        self.llm = llm

    def outline(self, idx: RepoIndex) -> Outline:
        """对索引跑完整 outliner 流水线。

        Args:
            idx: 仓库索引

        Returns:
            Outline 产物,含入口/机制候选/流程候选/模块候选;
            selected_mechanisms 暂为空,等 Task 5 接入 selector。
        """
        entries = find_entry_points(idx)
        entry_ids = [e.symbol_id for e in entries]
        mechanisms = find_mechanism_candidates(idx, top_k=20)
        flows = find_flow_candidates(idx, entry_symbol_ids=entry_ids)
        modules = find_module_candidates(idx, top_k=5)
        # Task 5 接入 selector 后启用
        # selected = select_mechanisms(self.llm, idx, mechanisms)
        selected: list = []
        return Outline(
            entry_points=entries,
            mechanism_candidates=mechanisms,
            flow_candidates=flows,
            module_candidates=modules,
            selected_mechanisms=selected,
        )
