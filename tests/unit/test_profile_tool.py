from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from taisang.user_profile.history import read_profile_history
from taisang.user_profile.store import load_profile, save_profile_content
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
    assert "content" in schema["parameters"]["properties"]
    assert "field" not in schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["content"]


def test_tool_run_writes_and_emits(tmp_path):
    """合法 content → 写盘 + emit 事件 + 返回生效文案。"""
    parent = MagicMock()
    tool = _make_tool(tmp_path, parent)
    result = tool.run({"content": "### 技术栈\nPython/Go"})

    # 写盘
    p = load_profile(settings_path=tmp_path / "settings.json")
    assert p.content == "### 技术栈\nPython/Go"

    # emit 事件
    parent._emit_profile_update.assert_called_once()
    call_kwargs = parent._emit_profile_update.call_args
    assert call_kwargs.kwargs["content"] == "### 技术栈\nPython/Go"

    # tool_result 文案
    assert "下次上下文压缩或新会话时生效" in result["content"]
    assert result["error"] is None


def test_tool_run_empty_content_clears(tmp_path):
    """空 content → 整篇置空。"""
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython", source="user", session_id=None, settings_path=sp)
    hp = tmp_path / "history.jsonl"
    parent = MagicMock()
    tool = UpdateProfileTool(
        session_id="s",
        parent_service=parent,
        settings_path=sp,
        history_path=hp,
    )

    tool.run({"content": ""})

    p = load_profile(settings_path=sp)
    assert p.content == ""


def test_tool_run_writes_history_with_agent_source(tmp_path):
    """agent 调工具 → history 记录 source=agent + session_id。"""
    tool = _make_tool(tmp_path)
    tool.run({"content": "### 技术栈\nPython"})

    records = read_profile_history(tmp_path / "history.jsonl")
    assert len(records) == 1
    assert records[0]["source"] == "agent"
    assert records[0]["session_id"] == "sess123"
    assert records[0]["field"] == "content"


def test_tool_name_property():
    tool = _make_tool(Path("/tmp"))
    assert tool.name == "update_profile"
