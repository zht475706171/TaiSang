"""outliner selector 单元测试——LLM 从候选里挑 5-10 个核心机制。"""

from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.outliner.selector import select_mechanisms
from code_reader.types import MechanismCandidate, RepoIndex


def test_select_mechanisms_llm_picks_5():
    """LLM 返回 JSON 含 5 个 symbol_id,selector 选出对应候选。"""
    cands = [
        MechanismCandidate(
            symbol_id=f"f{i}.py::m{i}",
            name=f"m{i}",
            file=f"f{i}.py",
            in_degree=10 - i,
            cross_module_refs=5,
            out_degree=3,
            score=100 - i,
        )
        for i in range(20)
    ]
    # LLM 返回前 5 个
    llm_resp = '{"selected": ["f0.py::m0", "f1.py::m1", "f2.py::m2", "f3.py::m3", "f4.py::m4"]}'
    mock = MockLLM([LLMResponse(text=llm_resp, tool_calls=[])])
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=[], files=[], index_errors=[])
    selected = select_mechanisms(mock, idx, cands)
    assert len(selected) == 5
    assert selected[0].symbol_id == "f0.py::m0"


def test_select_mechanisms_empty_candidates_returns_empty():
    """候选为空时直接返回空列表,不调用 LLM。"""
    mock = MockLLM([])
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=[], files=[], index_errors=[])
    selected = select_mechanisms(mock, idx, [])
    assert selected == []


def test_select_mechanisms_falls_back_on_bad_json():
    """LLM 返回非 JSON 时,fallback 取分数最高的前 min_count 个。"""
    cands = [
        MechanismCandidate(
            symbol_id=f"f{i}.py::m{i}",
            name=f"m{i}",
            file=f"f{i}.py",
            in_degree=10 - i,
            cross_module_refs=5,
            out_degree=3,
            score=100 - i,
        )
        for i in range(20)
    ]
    mock = MockLLM([LLMResponse(text="not a json", tool_calls=[])])
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=[], files=[], index_errors=[])
    selected = select_mechanisms(mock, idx, cands, min_count=3)
    assert len(selected) == 3
    # 候选已按 score 降序,fallback 取前 3
    assert selected[0].symbol_id == "f0.py::m0"


def test_select_mechanisms_fills_up_to_min_count():
    """LLM 只选了 2 个但 min_count=3 时,用高分候选补足到 3 个。"""
    cands = [
        MechanismCandidate(
            symbol_id=f"f{i}.py::m{i}",
            name=f"m{i}",
            file=f"f{i}.py",
            in_degree=10 - i,
            cross_module_refs=5,
            out_degree=3,
            score=100 - i,
        )
        for i in range(20)
    ]
    llm_resp = '{"selected": ["f0.py::m0", "f1.py::m1"]}'
    mock = MockLLM([LLMResponse(text=llm_resp, tool_calls=[])])
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=[], files=[], index_errors=[])
    selected = select_mechanisms(mock, idx, cands, min_count=3)
    assert len(selected) == 3
    assert selected[0].symbol_id == "f0.py::m0"
    assert selected[1].symbol_id == "f1.py::m1"
    # 第 3 个是高分补位
    assert selected[2].symbol_id == "f2.py::m2"
