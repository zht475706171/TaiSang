"""session_memory.should_extract 返回 trigger 原因字符串(非 bool)。

返回值:"init" / "update" / "idle_break" / ""(空串=不触发)。
"""

from pathlib import Path

from taisang.session_memory.service import SessionMemoryService


def _make_service(memory_path: Path) -> SessionMemoryService:
    return SessionMemoryService(llm=None, memory_path=memory_path)


def test_init_trigger_when_no_memory_and_tokens_high(tmp_path):
    """笔记不存在 + tokens >= MIN_TOKENS_TO_INIT → 返回 "init"。"""
    svc = _make_service(tmp_path / "note.md")
    assert svc.should_extract(current_tokens=10_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == "init"


def test_no_trigger_when_no_memory_but_tokens_low(tmp_path):
    """笔记不存在 + tokens < MIN_TOKENS_TO_INIT → 返回空串。"""
    svc = _make_service(tmp_path / "note.md")
    assert svc.should_extract(current_tokens=5000, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == ""


def test_update_trigger_when_delta_and_tools_met(tmp_path):
    """笔记存在 + delta_tokens + tool_calls 双满足 → 返回 "update"。"""
    svc = _make_service(tmp_path / "note.md")
    svc._last_extracted_tokens = 5000
    (tmp_path / "note.md").write_text("# 已有笔记\n一些内容", encoding="utf-8")
    assert svc.should_extract(current_tokens=15_001, tool_calls_since_last=5,
                              last_turn_has_tool_calls=True) == "update"


def test_idle_break_trigger_when_delta_met_and_no_tool_calls(tmp_path):
    """笔记存在 + delta_tokens 满足 + 最后一轮无工具调用 → 返回 "idle_break"。"""
    svc = _make_service(tmp_path / "note.md")
    svc._last_extracted_tokens = 5000
    (tmp_path / "note.md").write_text("# 已有笔记", encoding="utf-8")
    assert svc.should_extract(current_tokens=15_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=False) == "idle_break"


def test_no_trigger_when_already_extracting(tmp_path):
    """正在提取中 → 返回空串(不并发触发)。"""
    svc = _make_service(tmp_path / "note.md")
    svc._extracting = True
    assert svc.should_extract(current_tokens=10_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == ""


def test_empty_string_is_falsy():
    """空串应该是 falsy(调用方 `if reason:` 能正常用)。"""
    assert not ""
    assert "init"