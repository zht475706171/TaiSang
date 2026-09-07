"""LLM endpoint 配置加载 + 保存。

优先级: 文件(~/.taisang/settings.json) > env > 默认值。
前端写入后文件是真相源,env 仅在文件字段缺失时 fallback。
单一 LLM 配置(summarizer / agent 全用同一个模型)。
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
    return Path.home() / ".taisang" / "settings.json"


def _load_settings_file() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 损坏文件当空处理,fallback 到 env/默认
        return {}


def load_config() -> LLMConfig:
    """加载 LLM 配置。文件 > env > 默认。env 仅在文件字段缺失时 fallback。"""
    file_cfg = _load_settings_file().get("llm", {})
    # 文件优先,文件没的字段才看 env
    base_url = file_cfg.get("base_url") or os.environ.get("TAISANG_LLM_BASE_URL")
    api_key = file_cfg.get("api_key") or os.environ.get("TAISANG_LLM_API_KEY")
    model = file_cfg.get("model") or os.environ.get("TAISANG_LLM_MODEL")
    config_data = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }
    # Drop None values so Pydantic field defaults apply
    config_data = {k: v for k, v in config_data.items() if v is not None}
    return LLMConfig(**config_data)


def save_config(cfg: LLMConfig) -> None:
    """原子写 ~/.taisang/settings.json 的 llm 字段。保留其它字段。权限 600。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["llm"] = cfg.model_dump()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod,跳过
    os.replace(tmp, p)


def mask_api_key(key: str) -> str:
    """api_key 打码:前 3 + *** + 后 4,短于 8 字符全 ***。"""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


class SkillsConfig(BaseModel):
    """Skill 加载配置。"""

    user_dirs: list[Path] = []      # 用户级 skill 目录,默认 ~/.taisang/skills
    project_dirs: list[Path] = []   # 项目级 skill 目录,默认空(运行时补 source_root/.taisang/skills)


def load_skills_config() -> SkillsConfig:
    """加载 skills 配置。文件 ~/.taisang/settings.json 的 skills 字段 > 默认值。

    user_dirs 默认 ~/.taisang/skills。project_dirs 默认空(由 SessionRegistry 运行时
    拼上 source_root/.taisang/skills,这样不用每个项目都在 settings.json 配)。
    """
    file_cfg = _load_settings_file().get("skills", {})
    user_dirs = file_cfg.get("user_dirs")
    if user_dirs is None:
        user_dirs = [Path.home() / ".taisang" / "skills"]
    else:
        user_dirs = [Path(d) for d in user_dirs]
    project_dirs = [Path(d) for d in file_cfg.get("project_dirs", [])]
    return SkillsConfig(user_dirs=user_dirs, project_dirs=project_dirs)


# === Prompts 配置 ===

PROMPT_KEYS = frozenset(
    {
        "system_prompt",
        "autocompact_prompt",
        "session_memory_template",
        "session_memory_update_prompt",
    }
)

_PROMPT_MAX_BYTES = 50 * 1024


class PromptOverride(BaseModel):
    """单个 prompt 的覆盖配置。

    use_default=true 时运行时读代码常量,value 忽略;
    use_default=false 时运行时读 value。
    """

    value: str = ""
    use_default: bool = True


class PromptsConfig(BaseModel):
    """四份 prompt 的覆盖配置。"""

    system_prompt: PromptOverride = PromptOverride()
    autocompact_prompt: PromptOverride = PromptOverride()
    session_memory_template: PromptOverride = PromptOverride()
    session_memory_update_prompt: PromptOverride = PromptOverride()


def load_prompts() -> PromptsConfig:
    """加载 prompts 配置。settings.json 的 prompts 字段 > 默认(全 use_default=true)。

    损坏文件 fallback 到默认(复用 _load_settings_file 的容错)。
    """
    raw = _load_settings_file().get("prompts", {})
    if not isinstance(raw, dict):
        return PromptsConfig()
    # 逐字段构造,容忍部分缺失
    data = {}
    for key in PROMPT_KEYS:
        item = raw.get(key)
        if isinstance(item, dict):
            data[key] = PromptOverride(
                value=str(item.get("value", "")),
                use_default=bool(item.get("use_default", True)),
            )
        # 缺失的 key 用默认 PromptOverride(不写进 data,让 Pydantic 填默认)
    return PromptsConfig(**data)


def _save_prompts_section(prompts_dict: dict) -> None:
    """原子写 settings.json 的 prompts 字段,保留 llm/skills 等其他字段。权限 600。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["prompts"] = prompts_dict
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, p)


def _validate_prompt_value(value: str) -> None:
    """校验单 prompt 文本:非空且 UTF-8 字节数 ≤ 50KB(单 prompt 文本上限,非整个文件大小)。"""
    if not value:
        raise ValueError("prompt 不能为空")
    if len(value.encode("utf-8")) > _PROMPT_MAX_BYTES:
        raise ValueError(f"prompt 过长(>{_PROMPT_MAX_BYTES // 1024}KB)")


def _persist_prompts(cfg: PromptsConfig) -> PromptsConfig:
    """把 PromptsConfig 序列化 + 原子写盘。返回 cfg(便于链式返回)。"""
    raw = {k: getattr(cfg, k).model_dump() for k in PROMPT_KEYS}
    _save_prompts_section(raw)
    return cfg


def save_prompt_override(key: str, value: str) -> PromptsConfig:
    """保存单个 prompt 覆盖:use_default=false + 写 value。返回最新完整 config。

    校验:key 合法、value 非空且单文本 UTF-8 字节数 ≤ 50KB。
    """
    if key not in PROMPT_KEYS:
        raise ValueError(f"非法 key: {key}")
    _validate_prompt_value(value)
    cfg = load_prompts()
    setattr(cfg, key, PromptOverride(value=value, use_default=False))
    return _persist_prompts(cfg)


def reset_prompt_override(key: str) -> PromptsConfig:
    """恢复单个 prompt 为默认:use_default=true + 清空 value。返回最新完整 config。"""
    if key not in PROMPT_KEYS:
        raise ValueError(f"非法 key: {key}")
    cfg = load_prompts()
    setattr(cfg, key, PromptOverride())
    return _persist_prompts(cfg)
