"""Prompt 管理 API 路由:GET / PUT / RESET。

四份 prompt(system_prompt / autocompact_prompt / session_memory_template /
session_memory_update_prompt)持久化到 ~/.taisang/settings.json。
PUT/RESET system_prompt 时调 registry.apply_prompts_config 广播到所有活跃 session。
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

from ..agent_core.prompts import SYSTEM_PROMPT
from ..compaction.prompts import DEFAULT_AUTOCOMPACT_PROMPT
from ..config import (
    PROMPT_KEYS,
    load_prompts,
    reset_prompt_override,
    save_prompt_override,
)
from ..session_memory.template import DEFAULT_TEMPLATE, DEFAULT_UPDATE_PROMPT


class PromptSaveReq(BaseModel):
    """PUT /api/prompts 请求体。"""

    key: str
    value: str


class PromptResetReq(BaseModel):
    """POST /api/prompts/reset 请求体。"""

    key: str


# 默认值查表:GET 时返回每个 key 的 default(代码常量)
_DEFAULT_VALUES = {
    "system_prompt": SYSTEM_PROMPT,
    "autocompact_prompt": DEFAULT_AUTOCOMPACT_PROMPT,
    "session_memory_template": DEFAULT_TEMPLATE,
    "session_memory_update_prompt": DEFAULT_UPDATE_PROMPT,
}


def _build_response() -> dict:
    """组装响应:{ key: { current, default, use_default, value } }。

    value 字段始终返回(use_default 时为 None),保证 schema 稳定,前端无需 optional 处理。
    """
    cfg = load_prompts()
    result = {}
    for key in PROMPT_KEYS:
        override = getattr(cfg, key)
        default = _DEFAULT_VALUES[key]
        current = default if override.use_default or not override.value else override.value
        result[key] = {
            "current": current,
            "default": default,
            "use_default": override.use_default,
            "value": None if override.use_default else override.value,
        }
    return result


def register_prompts_routes(app, registry) -> None:
    """注册 /api/prompts 路由。registry 用于 broadcast system prompt 变更。"""

    @app.get("/api/prompts")
    async def get_prompts() -> dict:
        return _build_response()

    @app.put("/api/prompts")
    async def save_prompt(req: PromptSaveReq) -> dict:
        key = req.key
        value = req.value
        if key not in PROMPT_KEYS:
            raise HTTPException(400, f"非法 key: {key}")
        if not value:
            raise HTTPException(400, "value 不能为空")
        # autocompact_prompt 自定义文本必须含 {conversation} 占位符
        if key == "autocompact_prompt" and "{conversation}" not in value:
            raise HTTPException(400, "autocompact prompt 必须包含 {conversation} 占位符")
        try:
            save_prompt_override(key, value)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        # broadcast(只对 system_prompt 生效,其他 key registry 内部 no-op)
        registry.apply_prompts_config(key)
        return _build_response()

    @app.post("/api/prompts/reset")
    async def reset_prompt(req: PromptResetReq) -> dict:
        key = req.key
        if key not in PROMPT_KEYS:
            raise HTTPException(400, f"非法 key: {key}")
        try:
            reset_prompt_override(key)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        registry.apply_prompts_config(key)
        return _build_response()