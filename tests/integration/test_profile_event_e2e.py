"""集成测试:PROFILE_UPDATE 事件流。

验证 UpdateProfileTool.run → parent_service._emit_profile_update → _last_on_event
→ AgentEvent(type=PROFILE_UPDATE) 的完整事件链。
"""

from __future__ import annotations

from taisang.agent_core.events import PROFILE_UPDATE, AgentEvent
from taisang.user_profile.tool import UpdateProfileTool


def test_update_profile_tool_emits_profile_update_event(tmp_path):
    """agent 调 update_profile → emit PROFILE_UPDATE 事件(完整事件链)。"""
    sp = tmp_path / "settings.json"
    hp = tmp_path / "history.jsonl"

    events: list[AgentEvent] = []

    def capture_event(evt: AgentEvent):
        events.append(evt)

    # FakeParent 模拟 AgentService 的 _emit_profile_update + _last_on_event
    class FakeParent:
        def __init__(self):
            self._last_on_event = capture_event

        def _emit_profile_update(self, field, label, content, agent_id=""):
            self._last_on_event(
                AgentEvent(
                    type=PROFILE_UPDATE,
                    payload={"field": field, "label": label, "content": content, "source": "agent"},
                    agent_id=agent_id,
                )
            )

    parent = FakeParent()
    tool = UpdateProfileTool(
        session_id="sess1",
        parent_service=parent,
        settings_path=sp,
        history_path=hp,
    )
    tool.run({"field": "tech_stack", "content": "Python/Go"})

    assert len(events) == 1
    assert events[0].type == PROFILE_UPDATE
    assert events[0].payload["field"] == "tech_stack"
    assert events[0].payload["label"] == "技术栈"
    assert events[0].payload["content"] == "Python/Go"
    assert events[0].payload["source"] == "agent"
    assert events[0].agent_id == "sess1"


def test_profile_update_event_type_constant():
    """PROFILE_UPDATE 常量值稳定。"""
    assert PROFILE_UPDATE == "profile_update"