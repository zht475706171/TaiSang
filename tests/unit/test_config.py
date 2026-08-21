"""测试 LLM 配置加载(环境变量 / settings.json / 默认值)。"""

import json

from code_reader.config import load_config


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _clear_llm_env(monkeypatch):
    """清掉所有 LLM 相关 env, 让 settings.json / 默认值生效。"""
    for k in [
        "CODE_READER_LLM_BASE_URL",
        "CODE_READER_LLM_API_KEY",
        "CODE_READER_LLM_MODEL",
        "CODE_READER_SUMMARIZER_BASE_URL",
        "CODE_READER_SUMMARIZER_API_KEY",
        "CODE_READER_SUMMARIZER_MODEL",
    ]:
        monkeypatch.delenv(k, raising=False)


def test_config_from_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("CODE_READER_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("CODE_READER_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "deepseek-chat")
    cfg = load_config()
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.api_key == "sk-test"
    assert cfg.model == "deepseek-chat"


def test_config_from_settings_file(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".code-reader" / "settings.json"
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


def test_env_overrides_file(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".code-reader" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"llm": {"base_url": "https://from-file", "api_key": "k", "model": "m"}})
    )
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "from-env")
    cfg = load_config()
    assert cfg.model == "from-env"
    assert cfg.base_url == "https://from-file"


def test_summarizer_config_separate(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("CODE_READER_LLM_BASE_URL", "https://api.x.com")
    monkeypatch.setenv("CODE_READER_LLM_API_KEY", "k")
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "strong-model")
    monkeypatch.setenv("CODE_READER_SUMMARIZER_MODEL", "cheap-model")
    cfg = load_config()
    assert cfg.model == "strong-model"
    assert cfg.summarizer_model == "cheap-model"
