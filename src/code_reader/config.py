"""LLM endpoint 配置加载。

优先级: 环境变量 > ~/.code-reader/settings.json > 默认值。
单一 LLM 配置(summarizer / outliner / agent 全用同一个模型)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


class LLMConfig(BaseModel):
    """LLM 接入配置。"""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"


def _settings_path() -> Path:
    return Path.home() / ".code-reader" / "settings.json"


def _load_settings_file() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_config() -> LLMConfig:
    """加载 LLM 配置。env 覆盖文件,文件覆盖默认值。"""
    file_cfg = _load_settings_file().get("llm", {})
    base_url = os.environ.get("CODE_READER_LLM_BASE_URL", file_cfg.get("base_url"))
    api_key = os.environ.get("CODE_READER_LLM_API_KEY", file_cfg.get("api_key"))
    model = os.environ.get("CODE_READER_LLM_MODEL", file_cfg.get("model"))
    config_data = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }
    # Drop None values so Pydantic field defaults apply
    config_data = {k: v for k, v in config_data.items() if v is not None}
    return LLMConfig(**config_data)
