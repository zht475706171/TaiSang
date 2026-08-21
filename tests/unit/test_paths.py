"""测试路径管理(用 tmp_path 隔离,不污染真实 ~/.code-reader/)。

Windows 上 Path.home() 读 USERPROFILE, Linux/Mac 读 HOME。
两个 env 都 patch 以保证跨平台隔离。
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


def test_indices_dir(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    # repo_hash 是 url 的 sha1
    idx_dir = pm.indices_dir("https://github.com/test/repo")
    assert idx_dir.parent == pm.root / "indices"
    assert idx_dir.exists()


def test_cache_dir(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.cache_dir.exists()
