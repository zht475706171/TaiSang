"""selector:LLM 从候选机制里挑 5-10 个核心机制。

输入 mechanism_candidates(top 20),让 LLM 选 5-10 个最重要的,
返回带 one_liner 的子集。LLM 返回畸形时 fallback 取高分前 min_count 个。
"""

from __future__ import annotations

import json

from ..llm_client import LLMClient, MockLLM
from ..types import MechanismCandidate, RepoIndex

SELECTOR_SYSTEM = """你是一个代码库专家。从下面的候选机制里挑 5-10 个"这个项目最重要的机制"。
返回 JSON:{"selected": ["symbol_id1", "symbol_id2", ...], "reasons": {"symbol_id": "一句话定位"}}
只返回 JSON,不要其他文字。"""


def select_mechanisms(
    llm: LLMClient | MockLLM,
    idx: RepoIndex,
    candidates: list[MechanismCandidate],
    min_count: int = 3,
    max_count: int = 10,
) -> list[MechanismCandidate]:
    """让 LLM 从候选里选 5-10 个核心机制。

    Args:
        llm: LLM 客户端(真实或 Mock)
        idx: 仓库索引(传给 LLM 做上下文,目前未使用额外字段)
        candidates: 排序后的候选机制列表(top 20)
        min_count: 最少选出多少个,不足时用高分补位
        max_count: 最多选出多少个

    Returns:
        LLM 选中的候选子集,每个带 one_liner;LLM 返回畸形时 fallback 高分前 min_count 个。
    """
    if not candidates:
        return []
    cand_text = "\n".join(
        f"- {c.symbol_id} (in_degree={c.in_degree}, cross_module={c.cross_module_refs}, "
        f"score={c.score})"
        for c in candidates
    )
    user_prompt = f"候选机制(top 20):\n{cand_text}\n\n请挑 {min_count}-{max_count} 个最重要的。"
    resp = llm.chat(
        messages=[
            {"role": "system", "content": SELECTOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        tools=[],
    )
    try:
        data = json.loads(resp.text)
        selected_ids = data.get("selected", [])[:max_count]
    except (json.JSONDecodeError, AttributeError):
        # fallback:取分数最高的前 min_count 个
        return candidates[:min_count]
    reasons = data.get("reasons", {}) if isinstance(data, dict) else {}
    by_id = {c.symbol_id: c for c in candidates}
    result: list[MechanismCandidate] = []
    for sid in selected_ids:
        if sid in by_id:
            c = by_id[sid].model_copy()
            c.one_liner = reasons.get(sid, "")
            result.append(c)
    # 不足 min_count 用高分补
    if len(result) < min_count:
        existing = {c.symbol_id for c in result}
        for c in candidates:
            if c.symbol_id not in existing:
                result.append(c)
                if len(result) >= min_count:
                    break
    return result
