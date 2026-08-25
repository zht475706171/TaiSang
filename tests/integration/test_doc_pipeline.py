# tests/integration/test_doc_pipeline.py
"""端到端测试:doc 命令从 indexer → summarizer → outliner → docgen → agent 全流程。

用 CODE_READER_MOCK_LLM=1 跑 MockLLM,验证产物文件存在。
"""

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
    """建一个含 2 个 .py 的小 repo,git init/add/commit。"""
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from svc import handle\n\n"
        "def main():\n"
        "    handle()\n"
        "    print('done')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (repo / "svc.py").write_text(
        "def handle():\n" "    return process()\n\n" "def process():\n" "    return 42\n",
        encoding="utf-8",
    )
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
    return repo


def test_doc_pipeline_end_to_end(tmp_path, monkeypatch):
    """端到端:doc 命令应跑完全流程并落盘文档树。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)

    runner = CliRunner()
    r = runner.invoke(cli, ["doc", str(repo)])
    assert r.exit_code == 0, r.output
    # 产物存在
    doc_dir = repo / ".code-reader" / "docs"
    assert (doc_dir / "REPO_GUIDE.md").exists()
    assert (doc_dir / "00_项目是什么.md").exists()
    assert (doc_dir / "01_架构总览.md").exists()
    # 机制章节目录存在(outliner 选了至少 1 个机制)
    assert (doc_dir / "02_核心机制").is_dir()
    # CLI 流程跑完(三段进度提示任一)
    assert "AST 解析完成" in r.output or "agent 开始生成" in r.output or "文档生成完成" in r.output


def test_doc_pipeline_force_flag(tmp_path, monkeypatch):
    """--force 重写占位文件,仍然 exit_code 0。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)

    runner = CliRunner()
    # 第一次跑
    r1 = runner.invoke(cli, ["doc", str(repo)])
    assert r1.exit_code == 0, r1.output
    # 第二次带 --force,应仍然成功
    r2 = runner.invoke(cli, ["doc", str(repo), "--force"])
    assert r2.exit_code == 0, r2.output
    assert (repo / ".code-reader" / "docs" / "REPO_GUIDE.md").exists()
