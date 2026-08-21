"""测试 repo 抓取。用本地 git init 造 fixture,不依赖网络。"""

import os
import subprocess
from pathlib import Path

from code_reader.indexer.fetcher import Fetcher


def _make_local_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下造一个本地 git repo,含 2 个 .py 文件。"""
    repo = tmp_path / "fake-remote"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (repo / "b.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


def test_fetch_clones_local_repo(tmp_path):
    remote = _make_local_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    local_path, commit = fetcher.fetch(str(remote))
    assert local_path.exists()
    assert (local_path / "a.py").exists()
    assert (local_path / "b.py").exists()
    assert len(commit) > 0


def test_fetch_returns_same_path_for_already_cloned(tmp_path):
    remote = _make_local_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    p1, _ = fetcher.fetch(str(remote))
    p2, _ = fetcher.fetch(str(remote))
    assert p1 == p2


def test_fetch_invalid_url_raises(tmp_path):
    import pytest

    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    with pytest.raises(RuntimeError, match="clone failed"):
        fetcher.fetch("/nonexistent/path/that/does/not/exist")
