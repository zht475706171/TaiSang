"""BM25 索引:基于 rank_bm25 库,封装成 key-based 检索。"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    # 简单分词:中英文混合,英文按非字母数字切,中文按字切
    tokens: list[str] = []
    for chunk in re.findall(r"[a-zA-Z0-9_]+|[一-龥]", text):
        if re.match(r"[一-龥]", chunk):
            tokens.extend(list(chunk))
        else:
            tokens.append(chunk.lower())
    return tokens


class BM25Index:
    """key → text 的 BM25 索引。"""

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._pending: list[tuple[str, str]] = []

    def add(self, key: str, text: str) -> None:
        self._pending.append((key, text))

    def _build(self) -> None:
        if not self._pending:
            self._bm25 = None
            return
        self._keys = [k for k, _ in self._pending]
        corpus = [_tokenize(t) for _, t in self._pending]
        self._bm25 = BM25Okapi(corpus)
        self._pending = []

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if self._pending:
            self._build()
        if self._bm25 is None or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(
            zip(self._keys, scores.tolist(), strict=True),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:top_k]
