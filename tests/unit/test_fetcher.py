"""测试 Fetcher(本地 repo 探针,取 commit hash)。"""

import os
import subprocess
from pathlib import Path

from code_reader.indexer.fetcher import Fetcher


def _make_local_git_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下造一个本地 git repo,含 1 个 .py 文件。"""
    repo = tmp_path / "local-repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
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


def test_current_commit_returns_hash_for_git_repo(tmp_path):
    """有 .git 的本地 repo,返回 40 位 commit hash。"""
    repo = _make_local_git_repo(tmp_path)
    commit = Fetcher.current_commit(repo)
    assert len(commit) == 40  # sha1 hex


def test_current_commit_returns_unknown_for_non_git_dir(tmp_path):
    """无 .git 的目录,返回 'unknown'。"""
    repo = tmp_path / "no-git"
    repo.mkdir()
    (repo / "a.py").write_text("x", encoding="utf-8")
    assert Fetcher.current_commit(repo) == "unknown"


def test_current_commit_returns_unknown_when_git_not_installed(tmp_path):
    """git 未装 / subprocess 抛 FileNotFoundError,返回 'unknown' 不崩。"""
    repo = tmp_path / "fake"
    repo.mkdir()
    (repo / "a.py").write_text("x", encoding="utf-8")

    import code_reader.indexer.fetcher as fetcher_mod

    saved = fetcher_mod.subprocess.run

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    fetcher_mod.subprocess.run = fake_run
    try:
        assert Fetcher.current_commit(repo) == "unknown"
    finally:
        fetcher_mod.subprocess.run = saved
