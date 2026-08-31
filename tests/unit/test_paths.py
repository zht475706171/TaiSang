"""测试路径管理。

~/.code-reader/ 只保留 settings.json。
本地 repo 的会话/observation 等上下文管理产物落 <source_root>/.code-reader/。
"""

from code_reader.storage.paths import PathManager


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_root_default(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.root == tmp_path / ".code-reader"


def test_settings_path(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.settings_path == pm.root / "settings.json"


def test_session_memory_dir_under_code_reader(tmp_path):
    d = PathManager.session_memory_dir(tmp_path, "main")
    assert d == tmp_path / ".code-reader" / "sessions" / "main" / "session-memory"
    assert d.exists() and d.is_dir()


def test_session_memory_path_under_dir(tmp_path):
    p = PathManager.session_memory_path(tmp_path, "main")
    assert p == tmp_path / ".code-reader" / "sessions" / "main" / "session-memory" / "summary.md"


def test_observations_dir_under_code_reader(tmp_path):
    d = PathManager.observations_dir(tmp_path)
    assert d == tmp_path / ".code-reader" / "observations"
    assert d.exists() and d.is_dir()
