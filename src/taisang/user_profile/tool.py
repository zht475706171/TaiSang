"""UpdateProfileTool:LLM 调 update_profile({field, content}) 更新画像某一栏。

整栏覆盖。写盘 + 追加 history + emit PROFILE_UPDATE 事件。
不碰 ctx(system prompt 不变),当前 session 不立即生效,下次 autocompact 或新会话生效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent_core.tools import _BaseTool
from .history import append_profile_change
from .store import save_profile_field
from .types import PROFILE_FIELD_LABELS


class UpdateProfileTool(_BaseTool):
    """更新用户画像某一栏。整栏覆盖。"""

    name = "update_profile"

    def __init__(
        self,
        session_id: str,
        parent_service: Any,
        settings_path: Path | None = None,
        history_path: Path | None = None,
    ) -> None:
        self._session_id = session_id
        self._parent_service = parent_service
        self._settings_path = settings_path
        self._history_path = history_path

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "更新用户画像的某一栏。当从对话中发现用户的明确偏好/习惯/禁忌时调用"
                "(如用户说'我用 pnpm'、'别动 main 分支'、'中文回复')。"
                "整栏覆盖,调前确认你写的内容是该栏完整新版本。"
                "更新在下次上下文压缩或新会话时生效,当前会话不立即生效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "画像栏位",
                        "enum": ["tech_stack", "code_style", "communication", "environment", "taboos"],
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "该栏完整新内容(整栏覆盖)。建议精炼,5 栏总和建议 ≤500 字符,超长注入时截断。"
                        ),
                    },
                },
                "required": ["field", "content"],
            },
        }

    def run(self, args: dict) -> dict:
        field = args.get("field")
        content = args.get("content", "")

        # field 枚举校验(schema 层 OpenAI 会挡,这里兜底)
        if field not in PROFILE_FIELD_LABELS:
            return {
                "content": "",
                "error": f"非法 field: {field},可选: {list(PROFILE_FIELD_LABELS.keys())}",
            }

        # 写盘 + 拿 old 和 snapshot_before
        old, snapshot_before = save_profile_field(
            field=field,
            content=content,
            source="agent",
            session_id=self._session_id,
            settings_path=self._settings_path,
        )

        # 追加 history
        append_profile_change(
            field=field,
            old=old,
            new=content,
            source="agent",
            session_id=self._session_id,
            snapshot_before=snapshot_before,
            history_path=self._history_path,
        )

        # emit PROFILE_UPDATE 事件(前端 toast)
        label = PROFILE_FIELD_LABELS[field]
        emit = getattr(self._parent_service, "_emit_profile_update", None)
        if callable(emit):
            emit(field=field, label=label, content=content, agent_id=self._session_id)

        return {
            "content": f"用户画像【{label}】已更新。将在下次上下文压缩或新会话时生效,当前会话仍用旧画像。",
            "error": None,
        }