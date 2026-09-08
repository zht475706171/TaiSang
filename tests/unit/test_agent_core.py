"""测试 Agent 主循环。用 MockLLM 注入预设响应。"""

import json

from taisang.agent_core.confirm import AutoApproveConfirmer
from taisang.agent_core.service import AgentService
from taisang.llm_client import LLMResponse, MockLLM
from taisang.types import Answer


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
    from taisang.llm_errors import LLMProtocolError

    class BoomLLM:
        def chat(self, messages, tools):
            raise LLMProtocolError("malformed")
        def chat_stream(self, messages, tools):
            raise LLMProtocolError("malformed")
            yield  # unreachable,让函数成为 generator

    service = AgentService(llm=BoomLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    ans = service.run("q")
    assert ans.complete is False
    assert "LLM 协议错误" in ans.text
    assert ans.steps_used == 1


def test_agent_llm_protocol_error_emits_final_answer(tmp_path):
    """LLM 抛 LLMProtocolError 时,Agent 必须 emit FINAL_ANSWER 事件,前端能拿到错误回执。"""
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_errors import LLMProtocolError

    class BoomLLM:
        def chat(self, messages, tools):
            raise LLMProtocolError("malformed")
        def chat_stream(self, messages, tools):
            raise LLMProtocolError("malformed")
            yield

    service = AgentService(llm=BoomLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events: list = []
    service.run("q", on_event=lambda e: events.append(e))
    final = [e for e in events if e.type == FINAL_ANSWER]
    assert len(final) == 1, "异常路径必须 emit FINAL_ANSWER,前端才能显示错误"
    assert "LLM 协议错误" in final[0].payload["text"]


def test_agent_llm_transient_error_emits_final_answer(tmp_path):
    """LLM 抛 LLMTransientError(限流/网络)时,Agent 必须 emit FINAL_ANSWER。"""
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_errors import LLMTransientError

    class BoomLLM:
        def chat(self, messages, tools):
            raise LLMTransientError("429 rate-limited")
        def chat_stream(self, messages, tools):
            raise LLMTransientError("429 rate-limited")
            yield

    service = AgentService(llm=BoomLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events: list = []
    service.run("q", on_event=lambda e: events.append(e))
    final = [e for e in events if e.type == FINAL_ANSWER]
    assert len(final) == 1
    assert "LLM 调用失败" in final[0].payload["text"]
    assert "rate-limited" in final[0].payload["text"]


def test_agent_llm_error_emits_final_answer(tmp_path):
    """LLM 抛通用 LLMError 时,Agent 必须 emit FINAL_ANSWER。"""
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_errors import LLMError

    class BoomLLM:
        def chat(self, messages, tools):
            raise LLMError("unknown llm failure")
        def chat_stream(self, messages, tools):
            raise LLMError("unknown llm failure")
            yield

    service = AgentService(llm=BoomLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events: list = []
    service.run("q", on_event=lambda e: events.append(e))
    final = [e for e in events if e.type == FINAL_ANSWER]
    assert len(final) == 1
    assert "LLM 错误" in final[0].payload["text"]
    assert "unknown llm failure" in final[0].payload["text"]


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


class _UsageLLM:
    """假 LLM,每次返回固定 usage + 一次性最终答案,记录调用次数。"""

    def __init__(self, usage_list: list[dict]) -> None:
        self._usage_list = list(usage_list)
        self._i = 0

    def chat(self, messages, tools):
        from taisang.llm_client import LLMResponse

        usage = self._usage_list[self._i]
        self._i += 1
        return LLMResponse(text=f"ans-{self._i}", tool_calls=[], usage=usage)

    def chat_stream(self, messages, tools):
        from taisang.llm_stream import StreamChunk

        usage = self._usage_list[self._i]
        self._i += 1
        yield StreamChunk(text_delta=f"ans-{self._i}")
        yield StreamChunk(tool_calls=[], usage=usage, is_final=True)


def test_agent_accumulates_and_resets_token_usage(tmp_path):
    """AgentService 应累加 turn/session token,reset() 清零 session 累计。"""
    llm = _UsageLLM(
        [
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
            {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        ]
    )
    service = AgentService(llm=llm, source_root=tmp_path, confirmer=AutoApproveConfirmer())

    # 第 1 轮:turn = session = 150
    service.run("q1")
    assert service._turn_usage["total_tokens"] == 150
    assert service._session_usage["total_tokens"] == 150

    # 第 2 轮:turn = 280,session 累计 = 150 + 280 = 430
    service.run("q2")
    assert service._turn_usage["total_tokens"] == 280
    assert service._session_usage["total_tokens"] == 430

    # reset:session 累计清零
    service.reset()
    assert service._session_usage["total_tokens"] == 0
    assert service._turn_usage["total_tokens"] == 0

    # reset 后第 3 轮:turn = session = 70
    service.run("q3")
    assert service._turn_usage["total_tokens"] == 70
    assert service._session_usage["total_tokens"] == 70


def test_agent_usage_none_keeps_counters_zero(tmp_path):
    """LLM 返回 usage=None(MockLLM 路径)时,计数器保持 0,不报错。"""
    mock = MockLLM([LLMResponse(text="ans", tool_calls=[], usage=None)])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    service.run("q")
    assert service._turn_usage["total_tokens"] == 0
    assert service._session_usage["total_tokens"] == 0


def test_agent_emits_usage_report_event(tmp_path):
    """run() 结束应 emit USAGE_REPORT 事件,payload 含 turn/session/cache。"""
    from taisang.agent_core.events import USAGE_REPORT

    llm = _UsageLLM([{"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}])
    service = AgentService(llm=llm, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("q", on_event=lambda e: events.append(e))
    usage_events = [e for e in events if e.type == USAGE_REPORT]
    assert len(usage_events) == 1
    p = usage_events[0].payload
    assert p["turn"]["total"] == 15
    assert p["session"]["total"] == 15
    assert p["cache"]["available"] is False


def test_agent_service_on_append_propagates_to_ctx(tmp_path):
    """AgentService(on_append=...) 构造后,ctx.append_user 触发 on_append 回调。"""
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    collected: list[dict] = []
    agent = AgentService(
        llm=llm,
        source_root=tmp_path,
        confirmer=lambda file_path, old, new: True,
        on_append=lambda r: collected.append(r),
    )
    # 构造时 append_system(SYSTEM_PROMPT) 也触发 on_append(正确:system prompt
    # 也需落盘,resume 时才能恢复完整 ctx)。
    agent.ctx.append_user("hello")
    assert any(m == {"role": "user", "content": "hello"} for m in collected)
    assert collected[0]["role"] == "system"  # system prompt 先落盘


def test_agent_event_has_agent_id_field() -> None:
    """AgentEvent 支持 agent_id 字段(默认空字符串,主 agent 用空)。"""
    from taisang.agent_core.events import AgentEvent, TOOL_CALL
    evt = AgentEvent(type=TOOL_CALL, payload={"name": "Read"})
    assert evt.agent_id == ""  # 默认空
    evt2 = AgentEvent(type=TOOL_CALL, payload={"name": "Read"}, agent_id="child-123")
    assert evt2.agent_id == "child-123"


# --- Task 8: AgentService interrupt mechanism ---

def test_agent_service_interrupt_sets_cancel_event(tmp_path):
    """interrupt() set _cancel_event。"""
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
    )
    assert service._cancel_event is None
    service.run("test", on_event=None)
    assert service._cancel_event is not None
    service.interrupt()
    assert service._cancel_event.is_set() is True


def test_agent_service_interrupt_no_op_when_no_run(tmp_path):
    """interrupt() 在 run 之前调用无副作用。"""
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
    )
    service.interrupt()  # 无副作用,不抛


# --- Task 9: AgentService 流式主循环 ---

def test_run_streaming_emits_llm_chunk_events(tmp_path):
    """流式 run emit LLM_CHUNK 事件,累积 text_delta == FINAL_ANSWER text。"""
    from taisang.agent_core.events import LLM_CHUNK, FINAL_ANSWER

    mock = MockLLM([LLMResponse(text="hello world", tool_calls=[])])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("test", on_event=lambda e: events.append(e))
    chunk_events = [e for e in events if e.type == LLM_CHUNK]
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert len(chunk_events) >= 2
    text = "".join(e.payload.get("text_delta", "") for e in chunk_events)
    assert text == "hello world"
    assert final.payload["interrupted"] is False


def test_run_streaming_reasoning_delta(tmp_path):
    """reasoning_delta 流式 emit(MockLLM reasoning 字段)。"""
    from taisang.agent_core.events import LLM_CHUNK

    mock = MockLLM([LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("test", on_event=lambda e: events.append(e))
    reasoning = "".join(e.payload.get("reasoning_delta", "") for e in events if e.type == LLM_CHUNK)
    assert reasoning == "thinking process"


def test_run_streaming_interrupt_during_llm(tmp_path):
    """LLM 流式阶段中断:半截 text + [interrupted] 标记。"""
    from taisang.agent_core.events import FINAL_ANSWER, LLM_CHUNK

    mock = MockLLM([LLMResponse(text="a" * 50, tool_calls=[])])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    def on_event(e):
        events.append(e)
        if e.type == LLM_CHUNK and not service._cancel_event.is_set():
            service.interrupt()
    answer = service.run("test", on_event=on_event)
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert final.payload["interrupted"] is True
    assert "[interrupted]" in final.payload["text"]
    assert answer.interrupted is True


def test_run_streaming_interrupt_during_tool_execution(tmp_path):
    """工具执行阶段中断:补空 tool_result + [interrupted] 标记。"""
    from taisang.agent_core.events import FINAL_ANSWER, TOOL_CALL

    (tmp_path / "x.py").write_text("x = 1\n", encoding="utf-8")
    mock = MockLLM([
        LLMResponse(
            text="read file",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}],
        ),
        LLMResponse(text="final", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    def on_event(e):
        events.append(e)
        if e.type == TOOL_CALL and not service._cancel_event.is_set():
            service.interrupt()
    answer = service.run("test", on_event=on_event)
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert final.payload["interrupted"] is True
    assert answer.interrupted is True
    msgs = service.ctx.messages()
    tool_results = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_results) >= 1
    assert "_interrupted" in tool_results[0].get("content", "")


def test_run_streaming_mid_failure_no_retry(tmp_path):
    """流中失败(LLMTransientError after first chunk)不重试,标记 [LLM 调用失败]。"""
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_errors import LLMTransientError
    from taisang.llm_stream import StreamChunk

    class FakeLLM:
        def __init__(self):
            self.calls = []
        def chat(self, messages, tools):
            raise NotImplementedError
        def chat_stream(self, messages, tools):
            self.calls.append({"messages": messages, "tools": tools})
            yield StreamChunk(text_delta="partial")
            raise LLMTransientError("mid stream boom")

    service = AgentService(llm=FakeLLM(), source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    answer = service.run("test", on_event=lambda e: events.append(e))
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert "partial" in final.payload["text"]
    assert "[LLM 调用失败" in final.payload["text"]
    assert final.payload["interrupted"] is False


def test_run_streaming_interrupt_preserves_ctx_for_next_run(tmp_path):
    """中断后 ctx 保持 LLM API 兼容,下次 run 能继续。"""
    from taisang.agent_core.events import LLM_CHUNK, FINAL_ANSWER

    mock = MockLLM([
        LLMResponse(text="a" * 50, tool_calls=[]),
        LLMResponse(text="next answer", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    def on_event1(e):
        if e.type == LLM_CHUNK and not service._cancel_event.is_set():
            service.interrupt()
    service.run("first", on_event=on_event1)
    events2 = []
    service.run("second", on_event=lambda e: events2.append(e))
    final = [e for e in events2 if e.type == FINAL_ANSWER][0]
    assert final.payload["text"] == "next answer"
