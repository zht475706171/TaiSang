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


def test_repo_hash_stability(tmp_path, monkeypatch):
    """_repo_hash 必须稳定: 同 URL 同 hash, 不同 URL 不同 hash。

    锁定 sha1[:16] 契约, 防止后续重构静默破坏已索引数据的寻址。
    """
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    # 同一 URL 两次调用产出相同 hash
    h1 = pm._repo_hash("https://github.com/tiangolo/fastapi")
    h2 = pm._repo_hash("https://github.com/tiangolo/fastapi")
    assert h1 == h2
    # hash 是 16 字符 (sha1[:16])
    assert len(h1) == 16
    # 不同 URL 产出不同 hash (无碰撞)
    h3 = pm._repo_hash("https://github.com/pallets/flask")
    assert h3 != h1


def test_index_paths_under_indices_dir(tmp_path, monkeypatch):
    """四个 *_path 方法都应落在 indices_dir 下, 文件名正确。

    这是 Task 9 (storage) / Task 11 (indexer) 的依赖契约。
    """
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    repo_url = "https://github.com/test/repo"
    idx_dir = pm.indices_dir(repo_url)

    assert pm.index_db_path(repo_url) == idx_dir / "ast.db"
    assert pm.repo_map_path(repo_url) == idx_dir / "repo_map.json"
    assert pm.chroma_path(repo_url) == idx_dir / "chroma"
    assert pm.index_errors_path(repo_url) == idx_dir / "index_errors.json"
