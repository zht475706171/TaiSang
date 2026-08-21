"""测试混合检索。用 MockLLM 做 embedding,fallback 纯 BM25。"""

from code_reader.retriever.bm25 import BM25Index
from code_reader.retriever.hybrid import hybrid_rank
from code_reader.retriever.service import RetrieverService
from code_reader.types import FileSummary, GlobalSummary, ModuleSummary, RepoMap


def test_bm25_basic_search():
    idx = BM25Index()
    idx.add("a", "支付模块处理订单")
    idx.add("b", "用户登录认证")
    idx.add("c", "支付退款流程")
    results = idx.search("支付", top_k=2)
    assert len(results) == 2
    # a 和 c 跟"支付"相关,应该在 top 2
    files = {r[0] for r in results}
    assert files == {"a", "c"}


def test_bm25_empty_query_returns_empty():
    idx = BM25Index()
    idx.add("a", "hello")
    assert idx.search("", top_k=5) == []


def test_hybrid_rank_combines_vector_and_bm25():
    # 模拟两路打分
    vector_scores = [("a.py", 0.9), ("b.py", 0.5), ("c.py", 0.3)]
    bm25_scores = [("c.py", 2.0), ("b.py", 1.0), ("a.py", 0.0)]
    ranked = hybrid_rank(vector_scores, bm25_scores, vector_weight=0.7, bm25_weight=0.3)
    # a.py 向量分高,bm25 分低;综合下来应该靠前
    assert ranked[0][0] == "a.py"


def test_retriever_service_search_files():
    """端到端:基于 RepoMap 检索相关文件。"""
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={"": ModuleSummary(path="", summary="根模块", file_count=2)},
        file_summaries={
            "a.py": FileSummary(file="a.py", summary="处理支付订单的模块", symbol_ids=[]),
            "b.py": FileSummary(file="b.py", summary="用户登录认证模块", symbol_ids=[]),
        },
    )
    service = RetrieverService()
    service.build_from_repo_map(rm)
    snippets = service.search_files("支付", top_k=1)
    assert len(snippets) == 1
    assert snippets[0].file == "a.py"


def test_retriever_service_empty_query_returns_empty():
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={"a.py": FileSummary(file="a.py", summary="x", symbol_ids=[])},
    )
    service = RetrieverService()
    service.build_from_repo_map(rm)
    assert service.search_files("", top_k=5) == []
