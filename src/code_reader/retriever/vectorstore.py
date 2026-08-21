"""Chroma 向量库封装。

v1 简化:如果 embedding API 不可用(没配 key 或测试环境),fallback 到 BM25-only。
真正的 Chroma 集成留给后续,先做接口骨架。
"""

from __future__ import annotations

from typing import Protocol


class VectorStore(Protocol):
    """向量库接口。"""

    def add(self, key: str, text: str) -> None: ...
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...


class BM25OnlyStore:
    """无 embedding 时的 fallback:完全用 BM25。"""

    def __init__(self) -> None:
        from .bm25 import BM25Index

        self._idx = BM25Index()

    def add(self, key: str, text: str) -> None:
        self._idx.add(key, text)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return self._idx.search(query, top_k)
