"""测试上下文管理:token 估算 + compaction。"""

from taisang.agent_core.context import ContextManager


def test_estimate_tokens_approximate():
    cm = ContextManager(token_budget=32000)
    # 1 token ≈ 4 字符(英文),中文按 1.5 字符/token 估算,这里只测大致量级
    assert cm.estimate_tokens("hello world") > 0
    assert cm.estimate_tokens("你好世界") > 0


def test_within_budget_no_compaction():
    cm = ContextManager(token_budget=32000)
    cm.append_system("system prompt")
    cm.append_user("question")
    assert cm.should_compact() is False


def test_compaction_triggers_near_limit():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    # 塞大量内容触发
    cm.append_tool_result("x" * 4000, name="read_file")
    assert cm.should_compact() is True


def test_compact_keeps_system_and_recent():
    # keep_recent=1:只保留最近 1 条 tool_result,旧的会被压缩
    cm = ContextManager(token_budget=1000, keep_recent=1)
    cm.append_system("system prompt")
    cm.append_user("q1")
    cm.append_tool_result("old result" * 100, name="read_file")
    cm.append_tool_result("new result" * 100, name="grep")
    cm.compact()
    # compact 后 system 保留,旧 tool_result 被压缩成摘要
    msgs = cm.messages()
    assert msgs[0]["role"] == "system"
    # 旧的应该被压成摘要,不是原文
    text = "\n".join(m["content"] for m in msgs if isinstance(m.get("content"), str))
    assert "old result" not in text or "[compacted" in text


def test_compact_preserves_recent_observations():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    cm.append_tool_result("recent important" * 50, name="grep")
    cm.compact()
    msgs = cm.messages()
    # 最近的 observation 应该保留原文
    found = any("recent important" in m.get("content", "") for m in msgs)
    assert found


def test_total_tokens_after_compaction_within_budget():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    for _ in range(20):
        cm.append_tool_result("x" * 500, name="read_file")
    cm.compact()
    assert cm.total_tokens() < 1000


def test_on_append_called_on_each_append():
    """每次 append_user/assistant/tool_result 都触发 on_append 回调,传入完整 record。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    ctx.append_user("hello")
    ctx.append_assistant("hi", tool_calls=[{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}])
    ctx.append_tool_result("result", name="f", tool_call_id="t1")

    assert len(collected) == 3
    assert collected[0] == {"role": "user", "content": "hello"}
    assert collected[1]["role"] == "assistant"
    assert collected[1]["content"] == "hi"
    assert collected[1]["tool_calls"] is not None
    assert collected[2]["role"] == "tool"
    assert collected[2]["name"] == "f"
    assert collected[2]["tool_call_id"] == "t1"


def test_on_append_none_no_error():
    """on_append=None(默认)时不报错。"""
    ctx = ContextManager()
    ctx.append_user("hello")  # 不应抛异常
    assert len(ctx.messages()) == 1


def test_replace_messages_with_compaction_writes_boundary_and_new_msgs():
    """replace_messages(new_msgs, compaction_via='llm') 先写 boundary system record,再写新 messages。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    ctx.append_user("old")  # 这条也会被 on_append 捕获

    collected.clear()  # 只看 replace_messages 的输出
    new_msgs = [
        {"role": "user", "content": "[boundary]"},
        {"role": "user", "content": "summary..."},
    ]
    ctx.replace_messages(new_msgs, compaction_via="llm")

    # 第一条是 boundary system record
    assert collected[0]["role"] == "system"
    assert collected[0]["content"] == "[compacted via llm]"
    # 后面是 new_msgs 逐条
    assert collected[1] == new_msgs[0]
    assert collected[2] == new_msgs[1]
    # 内存已替换
    assert ctx.messages() == new_msgs


def test_replace_messages_without_compaction_via_no_boundary():
    """replace_messages(new_msgs) 不传 compaction_via 时不写 boundary(向后兼容)。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    new_msgs = [{"role": "user", "content": "x"}]
    ctx.replace_messages(new_msgs)
    # 不写 boundary,也不写新 messages 到 on_append(避免 enforce_budget 路径重复写)
    assert collected == []
    assert ctx.messages() == new_msgs


def test_load_from_records_truncates_to_last_boundary():
    """load_from_records 截断式 resume:只保留最后一条 boundary 之后的 records
    (boundary 之前的内容已被压缩成后面的 summary,灌回前面内容会造成 ctx 膨胀)。
    不触发 on_append(避免重复写盘)。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    records = [
        {"role": "user", "content": "q1"},  # boundary 前,被截掉
        {"role": "system", "content": "[compacted via llm]"},  # boundary
        {"role": "user", "content": "q2"},  # boundary 后,保留
    ]
    ctx.load_from_records(records)
    # 只保留 boundary 之后的 q2
    assert ctx.messages() == [{"role": "user", "content": "q2"}]
    # 不触发 on_append
    assert collected == []


def test_load_from_records_multiple_boundaries_keeps_only_last():
    """多次压缩:每次 boundary 都 supersede 前面所有内容,只灌回最后一个 boundary 后的。"""
    ctx = ContextManager()
    records = [
        {"role": "user", "content": "very old"},
        {"role": "system", "content": "[compacted via llm]"},
        {"role": "user", "content": "middle"},
        {"role": "system", "content": "[compacted via session_memory]"},  # 最后一个 boundary
        {"role": "user", "content": "after second compaction"},
    ]
    ctx.load_from_records(records)
    assert ctx.messages() == [{"role": "user", "content": "after second compaction"}]


def test_load_from_records_no_boundary_returns_all():
    """无 boundary(从未压缩过的新会话):灌回全部 records。"""
    ctx = ContextManager()
    records = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    ctx.load_from_records(records)
    assert ctx.messages() == records


def test_load_from_records_dedupes_repeated_system():
    """多次重启累积多条相同 SYSTEM_PROMPT,灌回时只保留第一条 system。
    场景:每次进程重启 AgentService.__init__ 都 append_system 一条到 jsonl,
    多次重启后 jsonl 有 N 条相同 system。灌回 ctx 只保留第一条,避免 LLM 困惑。"""
    ctx = ContextManager()
    records = [
        {"role": "system", "content": "system prompt"},  # 保留
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "system", "content": "system prompt"},  # 重启累积,丢弃
        {"role": "system", "content": "system prompt"},  # 再次重启,丢弃
        {"role": "user", "content": "q2"},
    ]
    ctx.load_from_records(records)
    # 只保留第一条 system,其余 system 丢弃
    system_count = sum(1 for m in ctx.messages() if m["role"] == "system")
    assert system_count == 1
    # user / assistant 都保留
    roles = [m["role"] for m in ctx.messages()]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 1
