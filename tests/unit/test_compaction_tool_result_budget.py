"""apply-tool-result-budget 的行为测试。

覆盖:
- 超预算的大 tool_result 被持久化 + preview 替换(核心)
- 决策冻结:第二次见到同一 tcid 直接套 preview(核心)
- 未超预算:不落盘、不替换、全部进 seen_ids
- SKIP_TOOL_NAMES 内的工具:即使超预算也不持久化
- 小于 persist_threshold:超预算但太小不值得持久化
"""

from __future__ import annotations

from taisang.compaction.tool_result_budget import (
    ContentReplacementState,
    enforce_budget,
)


def test_enforce_budget_persists_large_result(tmp_path):
    """超预算的 tool_result 被持久化到磁盘,content 替换为 preview 占位符。"""
    state = ContentReplacementState()
    # 一个 60KB 的 tool_result,超 50KB 持久化阈值;budget 调到 10KB 让总字节超预算
    big_content = "x" * 60_000
    messages = [
        {
            "role": "user",
            "content": "ctx",
            "tool_calls": [{"id": "tc1", "function": {"name": "read_file"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": big_content},
    ]
    new_messages, newly_replaced = enforce_budget(
        messages,
        state,
        persist_dir=tmp_path,
        budget_bytes=10_000,
    )
    assert len(newly_replaced) == 1
    assert newly_replaced[0]["tool_call_id"] == "tc1"
    # 替换后 content 含 preview + 文件路径提示
    tool_msg = next(m for m in new_messages if m["role"] == "tool")
    assert "[persisted-output]" in tool_msg["content"]
    assert "2,000" in tool_msg["content"] or "预览" in tool_msg["content"]
    # 决策冻结:tc1 进 seen_ids
    assert "tc1" in state.seen_ids
    # 文件真的落盘了
    assert len(list(tmp_path.glob("*.txt"))) == 1


def test_enforce_budget_decision_is_frozen(tmp_path):
    """第二次 enforce 时,已决策的 tool_use_id 直接套 preview,无文件 I/O。"""
    state = ContentReplacementState()
    state.seen_ids.add("tc1")
    state.replacements["tc1"] = "[persisted-output]\n固定 preview\n[/persisted-output]"
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "原内容"},
    ]
    new_messages, newly = enforce_budget(messages, state, persist_dir=tmp_path)
    assert newly == []  # 没新决策
    assert new_messages[0]["content"] == "[persisted-output]\n固定 preview\n[/persisted-output]"
    # 不应该有文件落盘
    assert len(list(tmp_path.glob("*.txt"))) == 0


def test_enforce_budget_under_budget_no_persist(tmp_path):
    """总字节没超 budget:不落盘、不替换,所有 tcid 进 seen_ids。"""
    state = ContentReplacementState()
    # 3 个 1KB 的 tool_result,总 3KB << 200KB budget
    messages = [
        {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "a" * 1000},
        {"role": "tool", "tool_call_id": "t2", "name": "read_file", "content": "b" * 1000},
        {"role": "tool", "tool_call_id": "t3", "name": "read_file", "content": "c" * 1000},
    ]
    new_messages, newly_replaced = enforce_budget(
        messages,
        state,
        persist_dir=tmp_path,
    )
    assert newly_replaced == []
    # 没文件落盘
    assert len(list(tmp_path.glob("*.txt"))) == 0
    # 三个 tcid 都进 seen_ids(决策冻结:下次再见不重算)
    assert state.seen_ids == {"t1", "t2", "t3"}
    # content 原样不动
    assert new_messages[0]["content"] == "a" * 1000
    assert state.replacements == {}


def test_enforce_budget_skip_tool_names_not_persisted(tmp_path):
    """SKIP_TOOL_NAMES 内的工具结果即使超预算也不持久化。"""
    state = ContentReplacementState()
    big = "x" * 250_000  # 250KB,超 200KB budget
    messages = [
        {"role": "tool", "tool_call_id": "w1", "name": "write_doc", "content": big},
    ]
    new_messages, newly_replaced = enforce_budget(
        messages,
        state,
        persist_dir=tmp_path,
    )
    # write_doc 在 SKIP_TOOL_NAMES,不进 fresh_to_check,不持久化
    assert newly_replaced == []
    assert len(list(tmp_path.glob("*.txt"))) == 0
    # 但 w1 仍标记为 seen(决策冻结)
    assert "w1" in state.seen_ids
    # content 原样
    assert new_messages[0]["content"] == big


def test_enforce_budget_persist_threshold_too_small(tmp_path):
    """超预算但单条 < persist_threshold:不持久化,直接进 seen_ids。"""
    state = ContentReplacementState()
    # 一条 30KB(< 50KB threshold),但 budget 故意调到 10KB 让总字节超预算
    messages = [
        {"role": "tool", "tool_call_id": "s1", "name": "read_file", "content": "x" * 30_000},
    ]
    new_messages, newly_replaced = enforce_budget(
        messages,
        state,
        persist_dir=tmp_path,
        budget_bytes=10_000,  # 故意调小,让 30KB 超预算
        persist_threshold=50_000,
    )
    # 太小不值得持久化
    assert newly_replaced == []
    assert len(list(tmp_path.glob("*.txt"))) == 0
    assert "s1" in state.seen_ids
    assert state.replacements == {}
    # content 原样
    assert new_messages[0]["content"] == "x" * 30_000


def test_enforce_budget_skips_infinity_tools(tmp_path):
    """max_result_size_chars=Infinity 的工具(如 read_file)永不持久化,即使 > 50K 阈值。

    对齐 claude-code toolResultStorage.ts:59-64: Read opt-out 持久化,
    理由"Read self-bounds; persisting its output to a file the model reads back
    with Read is circular"。
    """
    state = ContentReplacementState()
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 60_000},
        {"role": "tool", "tool_call_id": "tc2", "name": "Bash", "content": "y" * 60_000},
    ]
    tool_size_limits = {"read_file": float("inf"), "Bash": 30_000}
    new_msgs, replaced = enforce_budget(
        messages, state, tmp_path,
        budget_bytes=50_000,
        tool_size_limits=tool_size_limits,
    )
    # read_file(tc1) 不被持久化,content 原样
    assert new_msgs[0]["content"] == "x" * 60_000
    # Bash(tc2) 参与持久化(总 120K > 50K budget,60K > 50K threshold)
    assert new_msgs[1]["content"] != "y" * 60_000
    assert any(r["tool_call_id"] == "tc2" for r in replaced)
    assert not any(r["tool_call_id"] == "tc1" for r in replaced)
    # 两个都进 seen_ids(决策冻结)
    assert "tc1" in state.seen_ids
    assert "tc2" in state.seen_ids


def test_enforce_budget_default_tool_size_limits_100k(tmp_path):
    """没传 tool_size_limits 时,未知工具默认 100_000(参与持久化)。"""
    state = ContentReplacementState()
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "unknown_tool", "content": "x" * 60_000},
    ]
    new_msgs, replaced = enforce_budget(
        messages, state, tmp_path, budget_bytes=10_000,
    )
    # unknown_tool 默认 100K,60K > 50K persist_threshold,总 60K > 10K budget,持久化
    assert len(replaced) == 1
