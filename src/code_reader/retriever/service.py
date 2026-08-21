"""检索服务:基于 RepoMap 建索引,提供 search_files。

v1 简化:用 BM25-only(不依赖 embedding API,测试友好)。
embedding + Chroma 留给后续优化。
"""

from __future__ import annotations

from ..types import RepoMap, Snippet
from .bm25 import BM25Index


class RetrieverService:
    """检索服务。"""

    def __init__(self) -> None:
        self._bm25 = BM25Index()
        self._summaries: dict[str, str] = {}

    def build_from_repo_map(self, repo_map: RepoMap) -> None:
        """从 RepoMap 建文件级 BM25 索引。"""
        self._bm25 = BM25Index()
        self._summaries = {}
        for fp, fs in repo_map.file_summaries.items():
            self._bm25.add(fp, fs.summary)
            self._summaries[fp] = fs.summary

    def search_files(self, query: str, top_k: int = 5) -> list[Snippet]:
        """搜相关文件,返回 Snippet 列表。"""
        if not query.strip():
            return []
        results = self._bm25.search(query, top_k=top_k)
        snippets: list[Snippet] = []
        for fp, score in results:
            snippets.append(
                Snippet(
                    file=fp,
                    line_range=(1, 1),  # 文件级,行号占位
                    text=self._summaries.get(fp, ""),
                    score=float(score),
                )
            )
        return snippets

    def search_modules(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        """搜相关模块(v1 简单实现,用模块摘要建临时 BM25)。"""
        # 简化:v1 暂不实现独立模块索引,直接返回空,实际问答时 agent 会用 search_files
        return []
