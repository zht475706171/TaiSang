"""UpdateProfileTool:LLM 调 update_profile({content}) 整篇覆盖画像。

写盘 + 追加 history + emit PROFILE_UPDATE 事件。
不碰 ctx(system prompt 不变),当前 session 不立即生效,下次 autocompact 或新会话生效。

调用心智:agent 先读现有画像(从 system prompt 的 ## 用户画像 段拿),
自己拼接整篇新 content(在对应 ### 标题下追加新偏好行),再调本工具整篇覆盖。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent_core.tools import _BaseTool
from .history import append_profile_change
from .store import save_profile_content


class UpdateProfileTool(_BaseTool):
    """更新用户画像(整篇覆盖)。"""

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
                "更新用户画像(整篇覆盖)。当从对话中发现用户的明确偏好/习惯/禁忌时调用"
                "(如用户说'我用 pnpm'、'别动 main 分支'、'中文回复')。"
                "画像用 ### 标题分段(技术栈/代码风格/沟通/环境/禁忌),"
                "调前先从你的 system prompt 的 ## 用户画像 段读现有内容,"
                "在对应标题下追加新偏好行(换行分隔),拼接成完整新 content 再写回。"
                "更新在下次上下文压缩或新会话时生效,当前会话不立即生效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "画像完整新内容(整篇覆盖)。用 ### 技术栈 / ### 代码风格 / "
                            "### 沟通 / ### 环境 / ### 禁忌 标题分段,"
                            "标题下用自由文本写偏好。总长建议 ≤500 字符,超长注入时截断。"
                        ),
                    },
                },
                "required": ["content"],
            },
        }

    def run(self, args: dict) -> dict:
        content = args.get("content", "")

        # 写盘 + 拿 old 和 snapshot_before
        old, snapshot_before = save_profile_content(
            content=content,
            source="agent",
            session_id=self._session_id,
            settings_path=self._settings_path,
        )

        # 追加 history
        append_profile_change(
            field="content",
            old=old,
            new=content,
            source="agent",
            session_id=self._session_id,
            snapshot_before=snapshot_before,
            history_path=self._history_path,
        )

        # emit PROFILE_UPDATE 事件(前端 toast)
        emit = getattr(self._parent_service, "_emit_profile_update", None)
        if callable(emit):
            emit(content=content, agent_id=self._session_id)

        return {
            "content": ("用户画像已更新。将在下次上下文压缩或新会话时生效,当前会话仍用旧画像。"),
            "error": None,
        }
