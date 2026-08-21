"""混合排序:融合向量检索和 BM25 的分数。"""

from __future__ import annotations


def _normalize(scores: list[tuple[str, float]]) -> dict[str, float]:
    if not scores:
        return {}
    vals = [s for _, s in scores]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return {k: 1.0 for k, _ in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores}


def hybrid_rank(
    vector_scores: list[tuple[str, float]],
    bm25_scores: list[tuple[str, float]],
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """加权融合两路打分,返回 (key, fused_score) 降序列表。"""
    v = _normalize(vector_scores)
    b = _normalize(bm25_scores)
    keys = set(v.keys()) | set(b.keys())
    fused = {k: vector_weight * v.get(k, 0.0) + bm25_weight * b.get(k, 0.0) for k in keys}
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    if top_k:
        ranked = ranked[:top_k]
    return ranked
