"""测试路径管理。

本地 repo 索引产物落 <source_root>/.code-reader/。
~/.code-reader/ 只剩 settings.json。
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


def test_index_dir_creates_code_reader_subdir(tmp_path):
    """index_dir 返回 <source_root>/.code-reader/ 并自动创建。"""
    d = PathManager.index_dir(tmp_path)
    assert d == tmp_path / ".code-reader"
    assert d.exists() and d.is_dir()


def test_index_db_path_under_code_reader(tmp_path):
    p = PathManager.index_db_path(tmp_path)
    assert p == tmp_path / ".code-reader" / "ast.db"


def test_repo_map_path_under_code_reader(tmp_path):
    p = PathManager.repo_map_path(tmp_path)
    assert p == tmp_path / ".code-reader" / "repo_map.json"


def test_chroma_and_errors_paths(tmp_path):
    assert PathManager.chroma_path(tmp_path) == tmp_path / ".code-reader" / "chroma"
    assert (
        PathManager.index_errors_path(tmp_path) == tmp_path / ".code-reader" / "index_errors.json"
    )
