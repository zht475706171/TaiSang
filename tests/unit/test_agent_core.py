"""测试 Agent 主循环。用 MockLLM 注入预设响应。"""

import json

from code_reader.agent_core.confirm import AutoApproveConfirmer
from code_reader.agent_core.service import AgentService
from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.types import Answer


def _tc(call_id: str, name: str, args: dict) -> dict:
    """构造 OpenAI 标准 tool_call 结构。arguments 是 JSON 字符串。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


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
            LLMResponse(text="", tool_calls=[_tc("call_1", "read_file", {"path": "a.py"})]),
            LLMResponse(text="a.py 定义了 foo 函数", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("a.py 干啥的")
    assert "foo" in ans.text


def test_agent_max_steps_terminates(tmp_path):
    """Agent 一直调工具不回答,应超 max_steps 终止。"""
    mock = MockLLM(
        [LLMResponse(text="", tool_calls=[_tc("call_1", "read_file", {"path": "a.py"})])] * 20
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
            LLMResponse(text="", tool_calls=[_tc("call_1", "nonexistent_tool", {})]),
            LLMResponse(text="回答", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("q")
    assert ans.text == "回答"
    assert ans.steps_used == 2


def test_agent_malformed_tool_call_does_not_crash(tmp_path):
    """LLM 返回畸形 arguments JSON,Agent 不应崩,应记 malformed error 后继续到下一步回答。"""
    mock = MockLLM(
        [
            # 畸形 tool_call:arguments 是非法 JSON
            LLMResponse(
                text="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{bad json"},
                    }
                ],
            ),
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
            LLMResponse(text="", tool_calls=[_tc("call_1", "read_file", {"path": "big.py"})]),
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


def test_agent_multi_turn_remembers_previous_query(tmp_path):
    """REPL 多轮对话:第 2 轮 run() 应看到第 1 轮的 user/assistant/tool 消息(短期记忆)。

    验证 ContextManager 提到实例属性后,跨 run() 保留对话历史。
    """
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    mock = MockLLM(
        [
            # 第 1 轮:调 read_file 读 a.py
            LLMResponse(text="", tool_calls=[_tc("call_1", "read_file", {"path": "a.py"})]),
            # 第 1 轮:给出基于工具结果的回答
            LLMResponse(text="a.py 定义了 foo 函数", tool_calls=[]),
            # 第 2 轮:回答时提到上一轮问的 a.py(验证 LLM 看到了第 1 轮对话)
            LLMResponse(text="你刚才问的是 a.py", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())

    # 第 1 轮
    ans1 = service.run("读 a.py")
    assert "foo" in ans1.text

    # 第 2 轮:新 query,但 ctx 跨 run() 保留
    ans2 = service.run("我刚问了什么")
    assert "a.py" in ans2.text

    # 关键断言:第 2 轮调用 LLM 时,messages 应包含第 1 轮的 user query
    # mock.calls 索引:0=第1轮step1, 1=第1轮step2(answer), 2=第2轮step1
    second_turn_messages = mock.calls[2]["messages"]
    user_msgs = [m for m in second_turn_messages if m.get("role") == "user"]
    assert any(
        "读 a.py" in (m.get("content") or "") for m in user_msgs
    ), "第 2 轮 LLM 调用应看到第 1 轮的 user query(短期记忆生效)"
    # 也应包含第 1 轮的 tool result
    tool_msgs = [m for m in second_turn_messages if m.get("role") == "tool"]
    assert len(tool_msgs) >= 1


def test_agent_reset_clears_context(tmp_path):
    """reset() 后第 2 轮 run() 的 messages 不应包含第 1 轮的 query(短期记忆被清)。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    mock = MockLLM(
        [
            # 第 1 轮
            LLMResponse(text="", tool_calls=[_tc("call_1", "read_file", {"path": "a.py"})]),
            LLMResponse(text="a.py 定义了 foo", tool_calls=[]),
            # reset 后第 2 轮
            LLMResponse(text="新回答", tool_calls=[]),
        ]
    )
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())

    service.run("读 a.py")
    service.reset()
    ans2 = service.run("新问题")
    assert ans2.text == "新回答"

    # reset 后第 2 轮 LLM 调用的 messages 不应包含 "读 a.py"
    second_turn_messages = mock.calls[2]["messages"]
    all_content = " ".join(
        (m.get("content") or "") for m in second_turn_messages if isinstance(m.get("content"), str)
    )
    assert "读 a.py" not in all_content, "reset() 应清掉第 1 轮的对话历史"
