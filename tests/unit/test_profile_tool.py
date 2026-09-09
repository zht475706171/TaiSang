from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from taisang.user_profile.history import read_profile_history
from taisang.user_profile.store import load_profile, save_profile_field
from taisang.user_profile.tool import UpdateProfileTool


def _make_tool(tmp_path, parent_service=None):
    sp = tmp_path / "settings.json"
    hp = tmp_path / "history.jsonl"
    if parent_service is None:
        parent_service = MagicMock()
    return UpdateProfileTool(
        session_id="sess123",
        parent_service=parent_service,
        settings_path=sp,
        history_path=hp,
    )


def test_tool_schema_has_update_profile_name():
    tool = _make_tool(Path("/tmp"))
    schema = tool.schema()
    assert schema["name"] == "update_profile"
    assert "field" in schema["parameters"]["properties"]
    assert "content" in schema["parameters"]["properties"]
    assert "enum" in schema["parameters"]["properties"]["field"]
    assert set(schema["parameters"]["properties"]["field"]["enum"]) == {
        "tech_stack",
        "code_style",
        "communication",
        "environment",
        "taboos",
    }


def test_tool_run_valid_field_writes_and_emits(tmp_path):
    """合法 field → 写盘 + emit 事件 + 返回生效文案。"""
    parent = MagicMock()
    tool = _make_tool(tmp_path, parent)
    result = tool.run({"field": "tech_stack", "content": "Python/Go"})

    # 写盘
    p = load_profile(settings_path=tmp_path / "settings.json")
    assert p.tech_stack == "Python/Go"

    # emit 事件
    parent._emit_profile_update.assert_called_once()
    call_kwargs = parent._emit_profile_update.call_args
    assert call_kwargs.kwargs["field"] == "tech_stack"
    assert call_kwargs.kwargs["label"] == "技术栈"
    assert call_kwargs.kwargs["content"] == "Python/Go"

    # tool_result 文案
    assert "技术栈" in result["content"]
    assert "下次上下文压缩或新会话时生效" in result["content"]
    assert result["error"] is None


def test_tool_run_invalid_field_returns_error_no_write(tmp_path):
    """非法 field → 返回 error,不写盘。"""
    parent = MagicMock()
    tool = _make_tool(tmp_path, parent)
    result = tool.run({"field": "invalid_field", "content": "x"})

    assert result["content"] == ""
    assert "非法 field" in result["error"]
    parent._emit_profile_update.assert_not_called()

    # 没写盘
    p = load_profile(settings_path=tmp_path / "settings.json")
    assert p.tech_stack == ""


def test_tool_run_empty_content_clears_field(tmp_path):
    """空 content → 清空该栏。"""
    sp = tmp_path / "settings.json"
    # 先填一个值
    save_profile_field("tech_stack", "Python", source="user", session_id=None, settings_path=sp)
    hp = tmp_path / "history.jsonl"
    parent = MagicMock()
    tool = UpdateProfileTool(
        session_id="s", parent_service=parent, settings_path=sp, history_path=hp
    )

    tool.run({"field": "tech_stack", "content": ""})

    p = load_profile(settings_path=sp)
    assert p.tech_stack == ""


def test_tool_run_writes_history_with_agent_source(tmp_path):
    """agent 调工具 → history 记录 source=agent + session_id。"""
    tool = _make_tool(tmp_path)
    tool.run({"field": "tech_stack", "content": "Python"})

    records = read_profile_history(tmp_path / "history.jsonl")
    assert len(records) == 1
    assert records[0]["source"] == "agent"
    assert records[0]["session_id"] == "sess123"


def test_tool_name_property():
    tool = _make_tool(Path("/tmp"))
    assert tool.name == "update_profile"
