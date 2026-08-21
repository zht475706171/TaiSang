"""测试 CLI 入口:用 click 的 CliRunner 跑子命令。"""

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from code_reader.cli.main import cli


def _isolate_home(tmp_path, monkeypatch):
    """Windows: Path.home() 读 USERPROFILE;Linux/Mac 读 HOME。同时 patch。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    git_env["PATH"] = os.environ.get("PATH", "")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=git_env,
    )
    return repo


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "index" in result.output
    assert "ask" in result.output


def test_cli_index_command(tmp_path, monkeypatch):
    """index 命令应建索引并落盘到 <repo>/.code-reader/。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["index", str(repo)])
    assert result.exit_code == 0, result.output
    assert (repo / ".code-reader").exists()
    assert (repo / ".code-reader" / "ast.db").exists()
    assert (repo / ".code-reader" / "repo_map.json").exists()


def test_cli_ask_command_with_mock_llm(tmp_path, monkeypatch):
    """ask 命令用 MockLLM 应能跑通,返回字符串。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(repo)])
    result = runner.invoke(cli, ["ask", "main 函数干啥的", "--repo", str(repo)])
    assert result.exit_code == 0, result.output
    assert "main" in result.output or "mock" in result.output.lower()


def test_cli_index_rejects_nonexistent_path(tmp_path, monkeypatch):
    """路径不存在,index exit 1 + 错误提示。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    runner = CliRunner()
    result = runner.invoke(cli, ["index", str(tmp_path / "nonexistent")])
    assert result.exit_code == 1
    assert "路径不存在" in result.output or "not a directory" in result.output


def test_cli_ask_without_index_exits_1(tmp_path, monkeypatch):
    """未索引过的路径,ask exit 1 + 提示先 index。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "q", "--repo", str(repo)])
    assert result.exit_code == 1
    assert "未索引过" in result.output
