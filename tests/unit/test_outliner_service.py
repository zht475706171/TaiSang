"""OutlinerService 集成测试:验证 outline() 把 selector 接进来。"""

from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.outliner.service import OutlinerService
from code_reader.types import RepoIndex, Symbol, SymbolKind


def _make_index() -> RepoIndex:
    """构造一个有跨模块引用的最小 RepoIndex。

    a.py::hub 被 b/c/d 三个不同模块调用,是头号机制候选。
    """
    symbols = [
        Symbol(
            id="a.py::hub",
            kind=SymbolKind.FUNCTION,
            name="hub",
            file="a.py",
            line_range=(1, 5),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="b.py::user1",
            kind=SymbolKind.FUNCTION,
            name="user1",
            file="b.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
        Symbol(
            id="c.py::user2",
            kind=SymbolKind.FUNCTION,
            name="user2",
            file="c.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
        Symbol(
            id="d.py::user3",
            kind=SymbolKind.FUNCTION,
            name="user3",
            file="d.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
    ]
    return RepoIndex(
        source_root=".",
        commit_hash="x",
        symbols=symbols,
        files=["a.py", "b.py", "c.py", "d.py"],
        index_errors=[],
    )


def test_outline_selected_mechanisms_nonempty_and_from_candidates():
    """outline() 返回的 selected_mechanisms 非空,且每个元素都来自 mechanism_candidates。"""
    idx = _make_index()
    # 预跑一遍拿到候选 ID 集合
    from code_reader.outliner.mechanism_candidates import find_mechanism_candidates

    cands = find_mechanism_candidates(idx, top_k=20)
    cand_ids = {c.symbol_id for c in cands}
    # MockLLM 让 selector 选 hub
    llm_resp = '{"selected": ["a.py::hub"], "reasons": {"a.py::hub": "核心调度"}}'
    mock = MockLLM([LLMResponse(text=llm_resp, tool_calls=[])])
    svc = OutlinerService(llm=mock)
    outline = svc.outline(idx)
    assert outline.selected_mechanisms  # 非空
    for m in outline.selected_mechanisms:
        assert m.symbol_id in cand_ids


def test_outline_passes_llm_to_selector():
    """outline() 用注入的 LLM 调 selector,MockLLM 调用记录应留下 selector 的 prompt。"""
    idx = _make_index()
    llm_resp = '{"selected": ["a.py::hub"]}'
    mock = MockLLM([LLMResponse(text=llm_resp, tool_calls=[])])
    svc = OutlinerService(llm=mock)
    svc.outline(idx)
    # MockLLM 应被调用过
    assert len(mock.calls) >= 1
    # 最后一次(或某次)调用含 selector 的 system prompt
    found_selector = any(
        any(
            m.get("role") == "system" and "代码库专家" in m.get("content", "")
            for m in call["messages"]
        )
        for call in mock.calls
    )
    assert found_selector
