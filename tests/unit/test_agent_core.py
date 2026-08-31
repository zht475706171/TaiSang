"""测试 Agent 主循环。用 MockLLM 注入预设响应。"""

from code_reader.agent_core.confirm import AutoApproveConfirmer
from code_reader.agent_core.service import AgentService
from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.types import Answer


def test_agent_no_tool_calls_returns_answer_directly(tmp_path):
    mock = MockLLM([LLMResponse(text="直接回答:这是个空 repo", tool_calls=[])])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("这个 repo 是干啥的")
    assert isinstance(ans, Answer)
    assert "空 repo" in ans.text
    assert ans.complete is True
    assert ans.steps_used == 1


def test_agent_one_tool_call_then_answer(tmp_path):
    """Agent 先调 read_file 读 a.py,然后回答。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    mock = MockLLM(
        [
            LLMResponse(text="", tool_calls=[{"name": "read_file", "args": {"path": "a.py"}}]),
            LLMResponse(text="a.py 定义了 foo 函数", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("a.py 干啥的")
    assert "foo" in ans.text


def test_agent_max_steps_terminates(tmp_path):
    """Agent 一直调工具不回答,应超 max_steps 终止。"""
    mock = MockLLM(
        [LLMResponse(text="", tool_calls=[{"name": "read_file", "args": {"path": "a.py"}}])] * 20
    )  # 给够响应
    service = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
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
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("q")
    assert ans.text == "回答"
    assert ans.steps_used == 2


def test_agent_malformed_tool_call_does_not_crash(tmp_path):
    """LLM 返回缺 name 键的 tool_call,Agent 不应崩,应继续到下一步回答。"""
    mock = MockLLM(
        [
            # 畸形 tool_call:无 name 键
            LLMResponse(text="", tool_calls=[{"args": {"path": "a.py"}}]),
            LLMResponse(text="回答", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("q")
    # 应正常到第二步回答,不崩
    assert ans.text == "回答"
    assert ans.steps_used == 2


def test_agent_observation_truncation(tmp_path):
    """生成超大 observation,Agent 应截断并加 _truncated 标记。"""
    # 构造一个超大文件,让 read_file 返回接近上限的内容
    big_content = "x" * 40_000
    (tmp_path / "big.py").write_text(big_content, encoding="utf-8")
    mock = MockLLM(
        [
            LLMResponse(text="", tool_calls=[{"name": "read_file", "args": {"path": "big.py"}}]),
            LLMResponse(text="done", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("read big")
    assert ans.text == "done"
    # 验证 context 中 tool_result 被截断(查 messages 里的 tool role)
    tool_msgs = [m for m in mock.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    # 截断后 content 长度不应超过上限 + 标记后缀
    assert len(tool_msgs[0]["content"]) <= 33_000  # 32k 截断 + 标记后缀


def test_agent_llm_protocol_error_terminates(tmp_path):
    """LLM 抛 LLMProtocolError,Agent 应终止并返回 complete=False Answer。"""
    from code_reader.llm_errors import LLMProtocolError

    class BoomLLM:
        def chat(self, messages, tools):
            raise LLMProtocolError("malformed")

    service = AgentService(llm=BoomLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("q")
    assert ans.complete is False
    assert "LLM 协议错误" in ans.text
    assert ans.steps_used == 1
