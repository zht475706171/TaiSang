"""测试路径管理。

~/.taisang/ 保留 settings.json + sessions/。
session 产物按 session_id 落 ~/.taisang/sessions/<id>/,跟 repo 解耦。
"""

from taisang.storage.paths import PathManager


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_root_default(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.root == tmp_path / ".taisang"


def test_settings_path(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.settings_path == pm.root / "settings.json"


def test_sessions_dir_under_home(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    d = PathManager.sessions_dir()
    assert d == tmp_path / ".taisang" / "sessions"
    assert d.exists() and d.is_dir()


def test_session_memory_dir_under_home(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    d = PathManager.session_memory_dir("main")
    assert d == tmp_path / ".taisang" / "sessions" / "main" / "session-memory"
    assert d.exists() and d.is_dir()


def test_session_memory_path_under_dir(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    p = PathManager.session_memory_path("main")
    assert p == tmp_path / ".taisang" / "sessions" / "main" / "session-memory" / "summary.md"


def test_observations_dir_under_home(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    d = PathManager.observations_dir("test")
    assert d == tmp_path / ".taisang" / "sessions" / "test" / "observations"
    assert d.exists() and d.is_dir()


def test_migrate_legacy_sessions_moves_to_home(tmp_path, monkeypatch):
    """旧 source_root/.taisang/sessions/<id>/ 迁到 ~/.taisang/sessions/<id>/。"""
    _isolate_home(tmp_path, monkeypatch)
    # 旧目录
    legacy = tmp_path / "repo" / ".taisang" / "sessions" / "abc123"
    legacy.mkdir(parents=True)
    (legacy / "conversation.jsonl").write_text("{}", encoding="utf-8")
    source_root = tmp_path / "repo"

    count = PathManager.migrate_legacy_sessions(source_root)
    assert count == 1
    # 迁过去了
    dest = tmp_path / ".taisang" / "sessions" / "abc123" / "conversation.jsonl"
    assert dest.exists()
    # 旧目录被搬走
    assert not legacy.exists()


def test_migrate_legacy_sessions_skips_existing(tmp_path, monkeypatch):
    """目标已存在则跳过(不覆盖)。"""
    _isolate_home(tmp_path, monkeypatch)
    legacy = tmp_path / "repo" / ".taisang" / "sessions" / "abc123"
    legacy.mkdir(parents=True)
    (legacy / "conversation.jsonl").write_text("old", encoding="utf-8")

    dest_dir = tmp_path / ".taisang" / "sessions" / "abc123"
    dest_dir.mkdir(parents=True)
    (dest_dir / "conversation.jsonl").write_text("new", encoding="utf-8")

    count = PathManager.migrate_legacy_sessions(tmp_path / "repo")
    assert count == 0
    # 新内容没被覆盖
    assert (dest_dir / "conversation.jsonl").read_text(encoding="utf-8") == "new"


def test_migrate_legacy_sessions_no_legacy_dir(tmp_path, monkeypatch):
    """没有旧目录时返回 0,不报错。"""
    _isolate_home(tmp_path, monkeypatch)
    count = PathManager.migrate_legacy_sessions(tmp_path / "no-repo")
    assert count == 0