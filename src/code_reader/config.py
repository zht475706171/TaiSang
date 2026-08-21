"""LLM endpoint 配置加载。

优先级: 环境变量 > ~/.code-reader/settings.json > 默认值。
支持两套独立配置: 主模型(Agent 循环) 和 摘要模型(便宜模型)。
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
    # 摘要模型(可选,默认跟主模型一致)
    summarizer_base_url: str | None = None
    summarizer_api_key: str | None = None
    summarizer_model: str | None = None


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
    base_url = os.environ.get(
        "CODE_READER_LLM_BASE_URL", file_cfg.get("base_url", "https://api.openai.com/v1")
    )
    api_key = os.environ.get("CODE_READER_LLM_API_KEY", file_cfg.get("api_key", ""))
    model = os.environ.get("CODE_READER_LLM_MODEL", file_cfg.get("model", "gpt-4o"))
    summ_model = os.environ.get("CODE_READER_SUMMARIZER_MODEL", file_cfg.get("summarizer_model"))
    summ_base = os.environ.get(
        "CODE_READER_SUMMARIZER_BASE_URL", file_cfg.get("summarizer_base_url")
    )
    summ_key = os.environ.get("CODE_READER_SUMMARIZER_API_KEY", file_cfg.get("summarizer_api_key"))
    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        summarizer_base_url=summ_base,
        summarizer_api_key=summ_key,
        summarizer_model=summ_model,
    )
