"""测试 Agent 主循环。用 MockLLM 注入预设响应。"""

from code_reader.agent_core.service import AgentService
from code_reader.indexer.linker import CallGraphNode
from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.types import Answer, FileSummary, GlobalSummary, RepoMap


def _make_empty_repo_map() -> RepoMap:
    return RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={},
    )


def test_agent_no_tool_calls_returns_answer_directly(tmp_path):
    mock = MockLLM([LLMResponse(text="直接回答:这是个空 repo", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path, call_graph={}, repo_map=_make_empty_repo_map()
    )
    ans = service.run("这个 repo 是干啥的")
    assert isinstance(ans, Answer)
    assert "空 repo" in ans.text
    assert ans.complete is True
    assert ans.steps_used == 1


def test_agent_one_tool_call_then_answer(tmp_path):
    """Agent 先调 lookup_map,然后回答。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    mock = MockLLM(
        [
            LLMResponse(
                text="", tool_calls=[{"name": "lookup_map", "args": {"layer": "file", "query": ""}}]
            ),
            LLMResponse(text="a.py 定义了 foo 函数", tool_calls=[]),
        ]
    )
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={"a.py": FileSummary(file="a.py", summary="定义 foo 函数", symbol_ids=[])},
    )
    service = AgentService(llm=mock, source_root=tmp_path, call_graph={}, repo_map=rm)
    ans = service.run("a.py 干啥的")
    assert "foo" in ans.text


def test_agent_max_steps_terminates(tmp_path):
    """Agent 一直调工具不回答,应超 max_steps 终止。"""
    mock = MockLLM(
        [LLMResponse(text="", tool_calls=[{"name": "lookup_map", "args": {"layer": "global"}}])]
        * 20
    )  # 给够响应
    service = AgentService(
        llm=mock,
        source_root=tmp_path,
        call_graph={},
        repo_map=_make_empty_repo_map(),
        max_steps=3,
    )
    ans = service.run("q")
    assert ans.complete is False  # 提前终止
    assert ans.steps_used == 3


def test_agent_unknown_tool_does_not_crash(tmp_path):
    """LLM 调了不存在的工具,Agent 应记录错误 observation 继续。"""
    mock = MockLLM(
        [
            LLMResponse(text="", tool_calls=[{"name": "nonexistent_tool", "args": {}}]),
            LLMResponse(text="回答", tool_calls=[]),
        ]
    )
    service = AgentService(
        llm=mock, source_root=tmp_path, call_graph={}, repo_map=_make_empty_repo_map()
    )
    ans = service.run("q")
    assert ans.text == "回答"
    assert ans.steps_used == 2


def test_agent_trace_call_chain_in_answer(tmp_path):
    """Agent 用 trace_call_chain 追链路,答案里应体现链。"""
    graph = {
        "a.py::foo": CallGraphNode(
            "a.py::foo", "foo", "a.py", (1, 5), resolved_calls=["a.py::bar"], unresolved_calls=[]
        ),
        "a.py::bar": CallGraphNode(
            "a.py::bar", "bar", "a.py", (8, 12), resolved_calls=[], unresolved_calls=[]
        ),
    }
    mock = MockLLM(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    {"name": "trace_call_chain", "args": {"symbol_id": "a.py::foo", "depth": 2}}
                ],
            ),
            LLMResponse(text="调用链: foo → bar", tool_calls=[]),
        ]
    )
    service = AgentService(
        llm=mock, source_root=tmp_path, call_graph=graph, repo_map=_make_empty_repo_map()
    )
    ans = service.run("foo 调用了谁")
    assert "foo" in ans.text and "bar" in ans.text
