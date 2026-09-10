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


def test_agent_observation_not_truncated(tmp_path):
    """service.py 不再硬截断 observation,40KB 文件(< 256KB ReadFileTool 闸门)原样进 ctx。

    大 observation 持久化由 enforce_budget 50K 阈值管(Task 5-6),service.py 不再再加 32K 截断。
    """
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
    tool_msgs = [m for m in mock.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    # observation 原样进 ctx,不被 32K 截断。40KB 文件 < 256KB ReadFileTool 闸门,能完整读。
    # content 是 JSON {"content": "...", "truncated": false, "total_lines": N, "offset": 1, "error": null}
    # 长度应包含完整 40KB 内容 + JSON 包装
    assert len(tool_msgs[0]["content"]) > 40_000


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


def test_run_streaming_cancel_closes_raw_stream(tmp_path):
    """LLM 流式阶段 cancel:主线程调 raw_stream.close() 真关连接,pump 线程退出。

    对标 Claude Code abort signal:cancel 不只是设 flag,要真关 HTTP 连接,
    让阻塞中的 next() 抛异常退出,中断延迟从"等下一个 chunk"降到 ms 级。
    """
    import threading
    import time as _time
    from taisang.agent_core.events import FINAL_ANSWER, LLM_CHUNK, LLM_THINKING
    from taisang.llm_errors import LLMTransientError

    # 自定义 LLM:chat_stream 用阻塞 stream 模拟 LLM 长时间不吐 chunk
    class BlockingMockLLM:
        def __init__(self):
            self.calls = []
            self._raw_stream = None

        def chat(self, messages, tools):
            raise RuntimeError("not used")

        def chat_stream(self, messages, tools):
            from taisang.llm_stream import StreamChunk
            self.calls.append({"messages": messages, "tools": tools})
            class BlockingStream:
                def __init__(self):
                    self.close_calls = 0
                    self._closed = False
                def __iter__(self): return self
                def __next__(self):
                    while not self._closed:
                        _time.sleep(0.05)
                    raise RuntimeError("connection closed")
                def close(self):
                    self._closed = True
                    self.close_calls += 1
            stream = BlockingStream()
            self._raw_stream = stream
            # 暴露给 service.py 通过 _last_raw_stream close
            self._last_raw_stream = stream
            try:
                # 永远不会自然结束(阻塞),只能被 close
                while True:
                    if stream._closed:
                        raise RuntimeError("connection closed")
                    _time.sleep(0.05)
            except RuntimeError:
                raise LLMTransientError("LLM stream failed: connection closed")
            finally:
                stream.close()

    mock = BlockingMockLLM()
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    started = threading.Event()
    def on_event(e):
        events.append(e)
        if e.type == LLM_THINKING:
            started.set()
    # 在另一线程触发 cancel(模拟用户点 stop)
    def trigger_cancel():
        started.wait(timeout=2)
        _time.sleep(0.1)  # 等 pump 线程进入 next() 阻塞
        service.interrupt()
    threading.Thread(target=trigger_cancel, daemon=True).start()
    answer = service.run("test", on_event=on_event)
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert final.payload["interrupted"] is True
    assert answer.interrupted is True
    # raw stream 被 close(主线程 cancel 逻辑调的)
    assert mock._raw_stream.close_calls >= 1


def test_run_emits_todo_update_event(tmp_path):
    """LLM 调 TodoWrite 工具后,emit TODO_UPDATE 事件 + service.todos 更新。

    验证:TodoWriteTool 通过 service._emit_todo_update → _last_on_event emit 事件,
    前端能从 SSE 收到 todo_update。
    """
    from taisang.agent_core.events import FINAL_ANSWER, TODO_UPDATE, TOOL_CALL

    # MockLLM 第 1 轮调 TodoWrite 拆任务,第 2 轮给最终答案
    todo_args = json.dumps({"todos": [
        {"content": "读 service.py", "status": "in_progress", "activeForm": "正在读 service.py"},
        {"content": "总结核心逻辑", "status": "pending"},
    ]})
    mock = MockLLM([
        LLMResponse(
            text="",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "TodoWrite", "arguments": todo_args}}],
        ),
        LLMResponse(text="done", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("分析 service.py", on_event=lambda e: events.append(e))

    # TODO_UPDATE 事件被 emit
    todo_events = [e for e in events if e.type == TODO_UPDATE]
    assert len(todo_events) == 1
    payload = todo_events[0].payload
    assert len(payload["todos"]) == 2
    assert payload["todos"][0]["content"] == "读 service.py"
    assert payload["todos"][0]["status"] == "in_progress"
    assert payload["todos"][0]["activeForm"] == "正在读 service.py"
    assert todo_events[0].agent_id == ""  # 主 agent

    # service.todos 被覆盖式更新
    assert len(service.todos) == 2
    assert service.todos[0]["content"] == "读 service.py"

    # ToolCall 事件也发了(LLM 调 TodoWrite)
    tool_calls = [e for e in events if e.type == TOOL_CALL and e.payload.get("name") == "TodoWrite"]
    assert len(tool_calls) == 1


def test_todo_write_persists_across_runs(tmp_path):
    """todos 跨 run() 保留(用户能看到上一轮任务状态),reset 清空。"""
    from taisang.agent_core.events import TODO_UPDATE

    todo_args = json.dumps({"todos": [{"content": "任务1", "status": "in_progress"}]})
    mock = MockLLM([
        LLMResponse(
            text="",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "TodoWrite", "arguments": todo_args}}],
        ),
        LLMResponse(text="ok", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    service.run("start", on_event=lambda e: None)
    assert len(service.todos) == 1

    # 第二轮 run(不调 TodoWrite),todos 仍保留
    mock2 = MockLLM([LLMResponse(text="done", tool_calls=[])])
    service.llm = mock2
    service.run("continue", on_event=lambda e: None)
    assert len(service.todos) == 1  # 保留上一轮

    # reset 清空
    service.reset()
    assert service.todos == []


def test_session_memory_trigger_emits_compacted_event(tmp_path):
    """session_memory 触发 extract 时 emit COMPACTED 事件,payload 含 via + trigger。

    用 MockLLM 让对话超过 init 阈值(MIN_TOKENS_TO_INIT=10000),should_extract 返回 "init",
    _maybe_trigger_session_memory emit COMPACTED via=session_memory trigger=init。
    """
    from taisang.agent_core.events import COMPACTED
    from taisang.session_memory.service import SessionMemoryService
    from taisang.storage.paths import PathManager

    # 构造大文本让 ctx tokens 超过 10000(init 阈值)
    big_text = "x" * 40_000
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    session_mem = SessionMemoryService(
        llm=mock,
        memory_path=PathManager.session_memory_path(tmp_path, "test-session"),
    )
    service = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
        session_memory=session_mem,
    )
    # 灌大文本进 ctx(直接 append,user 消息)
    service.ctx.append_user(big_text)
    events = []
    service.run("继续", on_event=lambda e: events.append(e))
    compacted = [e for e in events if e.type == COMPACTED and e.payload.get("via") == "session_memory"]
    assert len(compacted) >= 1
    p = compacted[0].payload
    assert p["via"] == "session_memory"
    assert p["trigger"] in ("init", "update", "idle_break")
    assert "current_tokens" in p


def test_enforce_budget_emits_compacted_event(tmp_path, monkeypatch):
    """enforce_budget 持久化大 tool_result 时 emit COMPACTED 事件(stage=1, via=tool_result_budget)。

    构造超 50KB 的 tool_result,run 一轮,应看到 COMPACTED via=tool_result_budget payload。

    Task 4 已移除 service 的 _MAX_OBSERVATION_BYTES 32KB 硬截断,60KB tool_result 现在能
    完整进 ctx(60KB < 256KB ReadFileTool 闸门能读,service.py 不再二次截断),
    enforce_budget 50K persist_threshold 可达。
    """
    from taisang.agent_core.events import COMPACTED
    from taisang.agent_core.tools import ReadFileTool

    # 测试用 read_file 构造大 observation,但 ReadFileTool 默认 max_result_size_chars=Infinity
    # 会被 enforce_budget 跳过(opt-out 持久化)。这里 monkeypatch 覆写类属性为 100_000,
    # 让 read_file 在本测试里参与持久化,验证 enforce_budget 触发路径。
    monkeypatch.setattr(ReadFileTool, "max_result_size_chars", 100_000)

    # 单轮 4 条 60KB tool_result(总 240KB > 200KB budget,单条 60KB > 50KB persist_threshold)
    # 用 read_file 的 limit 参数绕过 ReadFileTool 自身的 32KB 字节闸门,拿全量内容
    big_content = "x" * 60_000
    for name in ("big1.txt", "big2.txt", "big3.txt", "big4.txt"):
        (tmp_path / name).write_text(big_content, encoding="utf-8")
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[
            _tc("c1", "read_file", {"path": "big1.txt", "limit": 99999}),
            _tc("c2", "read_file", {"path": "big2.txt", "limit": 99999}),
            _tc("c3", "read_file", {"path": "big3.txt", "limit": 99999}),
            _tc("c4", "read_file", {"path": "big4.txt", "limit": 99999}),
        ]),
        LLMResponse(text="done", tool_calls=[]),
        LLMResponse(text="done2", tool_calls=[]),
        LLMResponse(text="done3", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("读 big*.txt", on_event=lambda e: events.append(e))
    budget_events = [
        e for e in events
        if e.type == COMPACTED and e.payload.get("via") == "tool_result_budget"
    ]
    assert len(budget_events) >= 1
    p = budget_events[0].payload
    assert p["via"] == "tool_result_budget"
    assert "replaced" in p
    assert isinstance(p["replaced"], list)
    if p["replaced"]:
        assert "tool_call_id" in p["replaced"][0]


def test_autocompact_emits_tokens_in_payload(tmp_path):
    """autocompact 触发时 emit COMPACTED payload 含 before_tokens / after_tokens。

    构造大 ctx 让 should_compact 触发,MockLLM 给摘要响应,验证 COMPACTED via=llm
    payload 有 before_tokens(压缩前) + after_tokens(压缩后) + summary_messages(摘要条数)。
    """
    from taisang.agent_core.events import COMPACTED

    # 灌大文本让 ctx 超过 token_budget * compact_ratio 触发 should_compact
    big_text = "x" * 200_000
    mock = MockLLM([
        LLMResponse(text="<summary>摘要内容</summary>", tool_calls=[]),
        LLMResponse(text="最终答案", tool_calls=[]),
    ])
    service = AgentService(
        llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer(),
        token_budget=1000,  # 调小让大文本容易超
    )
    service.ctx.append_user(big_text)
    events = []
    service.run("继续", on_event=lambda e: events.append(e))
    llm_compacted = [
        e for e in events
        if e.type == COMPACTED and e.payload.get("via") == "llm"
    ]
    if llm_compacted:  # 触发了 autocompact 才校验
        p = llm_compacted[0].payload
        assert "before_tokens" in p
        assert "after_tokens" in p
        assert p["before_tokens"] > p["after_tokens"]
        assert "summary_messages" in p


def test_service_passes_tool_size_limits_to_enforce_budget(tmp_path, monkeypatch):
    """service.py 调 enforce_budget 时传 tool_size_limits={tool_name: max_result_size_chars}。

    read_file=Infinity 应被 enforce_budget 跳过(opt-out 持久化)。
    """
    from taisang.agent_core import service as service_mod

    # monkeypatch enforce_budget 捕获调用参数
    captured = {}

    def _fake_enforce_budget(messages, state, persist_dir, **kwargs):
        captured.update(kwargs)
        captured["messages_len"] = len(messages)
        return messages, []

    monkeypatch.setattr(service_mod, "enforce_budget", _fake_enforce_budget)

    # 跑一轮(调一个 read_file tool_call)
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[_tc("c1", "read_file", {"path": "a.py"})]),
        LLMResponse(text="done", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    service.run("read a", on_event=lambda e: None)

    # 断言 tool_size_limits 被传了
    assert "tool_size_limits" in captured
    limits = captured["tool_size_limits"]
    # read_file 应该是 Infinity
    assert limits.get("read_file") == float("inf")
    # Bash 应该是 30_000(如果注册了)
    if "Bash" in limits:
        assert limits["Bash"] == 30_000


def test_60kb_observation_triggers_enforce_budget_persist(tmp_path, monkeypatch):
    """60KB observation(超 50K persist_threshold)在生产路径能触发 enforce_budget 持久化。

    死代码复活验证:
    - Task 4 移除 service.py 32K 硬截断 → 60KB observation 原样进 ctx
    - Task 5-6 enforce_budget 传 tool_size_limits + 跳过 Infinity → read_file 默认 Infinity 被 opt-out
    - 这里 monkeypatch ReadFileTool.max_result_size_chars=100_000,让 read_file 参与持久化
    - 单轮 4 条 60KB tool_result(总 240KB > 200KB budget,单条 60KB > 50KB persist_threshold)
    - 断言:磁盘有持久化文件 + ctx 里 tool message content 被替换成 <persisted-output> 占位符
    """
    from taisang.agent_core.events import COMPACTED
    from taisang.agent_core.tools import ReadFileTool
    from taisang.storage.paths import PathManager

    # monkeypatch 让 read_file 参与持久化(默认 Infinity 被 opt-out)
    monkeypatch.setattr(ReadFileTool, "max_result_size_chars", 100_000)

    # 单轮 4 条 60KB tool_result(总 240KB > 200KB budget,单条 60KB > 50KB persist_threshold)
    big_content = "x" * 60_000
    for name in ("big1.txt", "big2.txt", "big3.txt", "big4.txt"):
        (tmp_path / name).write_text(big_content, encoding="utf-8")
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[
            _tc("c1", "read_file", {"path": "big1.txt", "limit": 99999}),
            _tc("c2", "read_file", {"path": "big2.txt", "limit": 99999}),
            _tc("c3", "read_file", {"path": "big3.txt", "limit": 99999}),
            _tc("c4", "read_file", {"path": "big4.txt", "limit": 99999}),
        ]),
        LLMResponse(text="done", tool_calls=[]),
    ])
    # token_budget 调大避免 240KB observation 触发 autocompact(stage-2)干扰本测试。
    # 本测试聚焦 stage-1 enforce_budget 持久化,autocompact 是另一道压缩不该混入。
    service = AgentService(
        llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer(),
        token_budget=200_000,
    )
    events = []
    service.run("读 big*.txt", on_event=lambda e: events.append(e))

    # 断言 1:emit 了 COMPACTED via=tool_result_budget 事件
    budget_events = [
        e for e in events
        if e.type == COMPACTED and e.payload.get("via") == "tool_result_budget"
    ]
    assert len(budget_events) >= 1, "应触发 stage-1 enforce_budget 持久化"

    # 断言 2:payload 含 replaced 列表(持久化的 tool_call_id + path)
    p = budget_events[0].payload
    assert "replaced" in p
    assert isinstance(p["replaced"], list)
    assert len(p["replaced"]) >= 1
    replaced_tcids = {r["tool_call_id"] for r in p["replaced"]}

    # 断言 3:磁盘上有持久化文件(observations_dir 下有 {tcid}.txt)
    observations_dir = PathManager.observations_dir(tmp_path)
    persist_files = list(observations_dir.glob("*.txt"))
    assert len(persist_files) >= 1, f"应至少持久化 1 个文件,实际 {persist_files}"

    # 断言 4:持久化文件内容是原 60KB observation(全量,不截断)
    for pf in persist_files:
        content = pf.read_text(encoding="utf-8")
        assert len(content) > 50_000, f"持久化文件应含全量 60KB observation,实际 {len(content)} 字节"
        assert "x" * 100 in content  # 内容正确

    # 断言 5:ctx 里 tool message content 被替换成 <persisted-output> 占位符
    # 看最后一次 LLM 调用的 messages(应含被替换的 tool messages)
    last_call_messages = mock.calls[-1]["messages"]
    tool_msgs = [m for m in last_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 4
    persisted_tool_msgs = [m for m in tool_msgs if "[persisted-output]" in m.get("content", "")]
    assert len(persisted_tool_msgs) >= 1, "至少 1 条 tool message 应被替换成 <persisted-output> 占位符"
