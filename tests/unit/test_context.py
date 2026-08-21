"""测试上下文管理:token 估算 + compaction。"""

from code_reader.agent_core.context import ContextManager


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
