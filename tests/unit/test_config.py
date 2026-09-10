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


def test_config_from_env(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
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


def test_file_overrides_env(tmp_path, monkeypatch):
    """决策 7:文件 > env > 默认。前端写入后文件是真相源,env 不 override。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"llm": {"base_url": "https://from-file", "api_key": "k-file", "model": "m-file"}})
    )
    monkeypatch.setenv("TAISANG_LLM_MODEL", "from-env")
    cfg = load_config()
    # 文件优先,env 被 override
    assert cfg.model == "m-file"
    assert cfg.base_url == "https://from-file"
    assert cfg.api_key == "k-file"


from taisang.config import save_config, mask_api_key, LLMConfig


def test_save_config_writes_llm_field(tmp_path, monkeypatch):
    """save_config 原子写 settings.json 的 llm 字段。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    cfg = LLMConfig(base_url="https://api.test.com", api_key="sk-abc12345", model="test-model")
    save_config(cfg)
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "https://api.test.com"
    assert data["llm"]["api_key"] == "sk-abc12345"
    assert data["llm"]["model"] == "test-model"


def test_save_config_preserves_other_fields(tmp_path, monkeypatch):
    """save_config 保留 settings.json 的其它字段(只改 llm)。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    p = tmp_path / ".taisang" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"other_field": "keep_me", "llm": {"base_url": "old", "api_key": "old", "model": "old"}}))
    cfg = LLMConfig(base_url="new", api_key="new-k", model="new-m")
    save_config(cfg)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["other_field"] == "keep_me"  # 保留
    assert data["llm"]["base_url"] == "new"  # 覆盖


def test_mask_api_key():
    """api_key 打码:前3+***+后4,短于8字符全 ***。"""
    assert mask_api_key("sk-f1575dabc663ec6df17433c4b8396ed2fd8fc17cf9f97a09454b37db38db53b6") == "sk-***53b6"
    assert mask_api_key("short") == "***"
    assert mask_api_key("") == "***"
    assert mask_api_key("12345678") == "***"  # 正好 8 字符,全 ***
    assert mask_api_key("123456789") == "123***6789"


def test_debug_default_false(tmp_path, monkeypatch):
    """LLMConfig.debug 默认 False,settings.json 无 debug 字段时 False。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    cfg = load_config()
    assert cfg.debug is False


def test_debug_from_settings_file(tmp_path, monkeypatch):
    """settings.json 有 debug:true → load_config 读到 True。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {"llm": {"base_url": "https://x", "api_key": "k", "model": "m", "debug": True}}
        )
    )
    cfg = load_config()
    assert cfg.debug is True


def test_save_config_writes_debug(tmp_path, monkeypatch):
    """save_config 把 debug 字段写入 settings.json。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    cfg = LLMConfig(base_url="https://x", api_key="k", model="m", debug=True)
    save_config(cfg)
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["debug"] is True


def test_save_config_preserves_debug_false(tmp_path, monkeypatch):
    """save_config debug=False 时写入 False(不是省略)。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    cfg = LLMConfig(base_url="https://x", api_key="k", model="m", debug=False)
    save_config(cfg)
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["debug"] is False
