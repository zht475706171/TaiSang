# tests/integration/test_doc_update.py
"""增量更新 --update 选项的端到端测试。

覆盖:
1. 已建过索引的 repo,改文件后 `doc --update` 应走增量,产物仍在,ast.db 不丢。
2. 全新 repo(没跑过 doc)调 `doc --update` 应自动 fallback 到 build,不崩。
3. `--update --force` 同时给时,走 build 路径(被 force 覆盖)。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from code_reader.cli.main import cli


def _isolate_home(tmp_path: Path, monkeypatch) -> None:
    """Windows: Path.home() 读 USERPROFILE;Linux/Mac 读 HOME。同时 patch。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")


def _git_init_commit(repo: Path) -> None:
    """对 repo 做 git init/add/commit,用临时身份避免读取全局 git config。"""
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=git_env,
    )


def test_doc_update_only_regenerates_changed(tmp_path: Path, monkeypatch) -> None:
    """改文件后 `doc --update` 应:exit_code==0、产物 REPO_GUIDE.md 仍在、
    ast.db 仍在(说明 indexer 走 update 而不是从零 build)、输出含「增量」。
    """
    _isolate_home(tmp_path, monkeypatch)

    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _git_init_commit(repo)

    runner = CliRunner()
    # 第一次全量
    r1 = runner.invoke(cli, ["doc", str(repo)])
    assert r1.exit_code == 0, r1.output
    doc_dir = repo / ".code-reader" / "docs"
    assert (doc_dir / "REPO_GUIDE.md").exists()
    ast_db = repo / ".code-reader" / "ast.db"
    assert ast_db.exists(), "首次全量后 ast.db 应存在"

    # 改 a.py
    (repo / "a.py").write_text("def foo():\n    return 2\n", encoding="utf-8")

    # 增量更新
    r2 = runner.invoke(cli, ["doc", str(repo), "--update"])
    assert r2.exit_code == 0, r2.output
    # 产物仍在
    assert (doc_dir / "REPO_GUIDE.md").exists()
    # ast.db 仍在(增量 update 复用已有库,不是从零重建)
    assert ast_db.exists(), "增量更新后 ast.db 应仍在"
    # 输出应表明走了增量分支
    assert "增量" in r2.output, f"输出应含「增量」字样,实际: {r2.output}"


def test_doc_update_first_time_falls_back_to_build(tmp_path: Path, monkeypatch) -> None:
    """全新 repo(没跑过 doc)调 `doc --update` 应自动 fallback 到 build,不崩。"""
    _isolate_home(tmp_path, monkeypatch)

    repo = tmp_path / "fresh"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _git_init_commit(repo)

    runner = CliRunner()
    # 直接 --update,没先跑全量
    r = runner.invoke(cli, ["doc", str(repo), "--update"])
    assert r.exit_code == 0, r.output
    doc_dir = repo / ".code-reader" / "docs"
    # 产物文件应存在(走的是 fallback build 路径)
    assert (doc_dir / "REPO_GUIDE.md").exists()
    # ast.db 应被建出来
    assert (repo / ".code-reader" / "ast.db").exists()


def test_doc_force_overrides_update(tmp_path: Path, monkeypatch) -> None:
    """同时给 `--update --force` 时应走 build 路径(force 覆盖 update)。

    断言:输出含 "AST 解析完成"(build 路径会 echo 这句),且产物文件存在。
    不强断言「不含增量」以免脆弱,但可断言 build 标志性输出存在。
    """
    _isolate_home(tmp_path, monkeypatch)

    repo = tmp_path / "force"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _git_init_commit(repo)

    runner = CliRunner()
    r = runner.invoke(cli, ["doc", str(repo), "--update", "--force"])
    assert r.exit_code == 0, r.output
    # 走 build 路径会有 "AST 解析完成" 这句 echo
    assert "AST 解析完成" in r.output, f"应走 build 路径,实际输出: {r.output}"
    doc_dir = repo / ".code-reader" / "docs"
    assert (doc_dir / "REPO_GUIDE.md").exists()
