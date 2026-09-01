"""测试 LLM 配置加载(环境变量 / settings.json / 默认值)。"""

import json

from taisang.config import load_config


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _clear_llm_env(monkeypatch):
    """清掉所有 LLM 相关 env, 让 settings.json / 默认值生效。"""
    for k in [
        "TAISANG_LLM_BASE_URL",
        "TAISANG_LLM_API_KEY",
        "TAISANG_LLM_MODEL",
    ]:
        monkeypatch.delenv(k, raising=False)


def test_config_from_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("TAISANG_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("TAISANG_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("TAISANG_LLM_MODEL", "deepseek-chat")
    cfg = load_config()
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.api_key == "sk-test"
    assert cfg.model == "deepseek-chat"


def test_config_from_settings_file(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "llm": {
                    "base_url": "https://api.openai.com",
                    "api_key": "sk-file",
                    "model": "gpt-4o",
                }
            }
        )
    )
    cfg = load_config()
    assert cfg.model == "gpt-4o"
    assert cfg.base_url == "https://api.openai.com"
    assert cfg.api_key == "sk-file"


def test_env_overrides_file(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"llm": {"base_url": "https://from-file", "api_key": "k", "model": "m"}})
    )
    monkeypatch.setenv("TAISANG_LLM_MODEL", "from-env")
    cfg = load_config()
    assert cfg.model == "from-env"
    assert cfg.base_url == "https://from-file"
