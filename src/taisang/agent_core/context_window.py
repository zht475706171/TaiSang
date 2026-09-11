"""Context window 解析 + autocompact 阈值计算。

对齐 claude-code 的设计:
- 三档 fallback:settings.json 显式配 > 环境变量 > 兜底 200K
- 阈值 = effective_window - autocompact_buffer
- effective_window = context_window - reserved_for_summary
- 熔断器:连续失败 N 次跳过后续 autocompact 尝试

claude-code 对应:
- MODEL_CONTEXT_WINDOW_DEFAULT = 200_000
- MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
- AUTOCOMPACT_BUFFER_TOKENS = 13_000
- MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# === 默认常量(对齐 claude-code) ===
DEFAULT_CONTEXT_WINDOW = 200_000          # claude-code MODEL_CONTEXT_WINDOW_DEFAULT
RESERVED_TOKENS_FOR_SUMMARY = 20_000      # claude-code MAX_OUTPUT_TOKENS_FOR_SUMMARY(上限)
AUTOCOMPACT_BUFFER_TOKENS = 13_000        # claude-code AUTOCOMPACT_BUFFER_TOKENS
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3  # claude-code 熔断阈值

# 环境变量名(测试/特殊场景 override 用)
ENV_MAX_CONTEXT_TOKENS = "TAISANG_MAX_CONTEXT_TOKENS"


def get_context_window(model: str, settings_path: Path | None = None) -> int:
    """解析模型的 context window 大小。

    三档 fallback(优先级从高到低):
    1. settings.json 的 model_context_window.<model> 精确匹配,
       或 model_context_window.default 兜底
    2. 环境变量 TAISANG_MAX_CONTEXT_TOKENS
    3. 兜底 DEFAULT_CONTEXT_WINDOW (200K)

    model 为空字符串时跳过精确匹配,走环境变量/兜底。
    配置损坏(JSON 解析失败/类型错)静默走 fallback,不抛异常。
    """
    # 1. settings.json 精确匹配 + default key
    if settings_path is not None:
        try:
            if settings_path.is_file():
                cfg = json.loads(settings_path.read_text(encoding="utf-8"))
                table = cfg.get("model_context_window")
                if isinstance(table, dict):
                    if model and model in table:
                        return int(table[model])
                    if "default" in table:
                        return int(table["default"])
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            pass  # 配置坏掉走 fallback,不阻塞

    # 2. 环境变量 override
    env_val = os.environ.get(ENV_MAX_CONTEXT_TOKENS)
    if env_val:
        try:
            parsed = int(env_val)
            if parsed > 0:
                return parsed
        except ValueError:
            pass

    # 3. 兜底
    return DEFAULT_CONTEXT_WINDOW


def get_autocompact_threshold(context_window: int) -> int:
    """计算 autocompact 触发阈值。

    threshold = effective_window - autocompact_buffer
    effective_window = context_window - reserved_for_summary

    默认 200K context_window 下:
    effective = 200K - 20K = 180K
    threshold = 180K - 13K = 167K (83.5%)
    """
    effective = context_window - RESERVED_TOKENS_FOR_SUMMARY
    return effective - AUTOCOMPACT_BUFFER_TOKENS