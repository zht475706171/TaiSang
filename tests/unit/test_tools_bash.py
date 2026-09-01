"""BashTool 测试(持久 shell 版)。

改造后 BashTool 用 PersistentShell(claude code 风格),cd 持久化。
测试要点:
- echo / git / python 跨平台稳的命令
- cd 持久化:cd 子目录后 pwd 看到新路径
- 危险命令黑名单(rm -rf / / mkfs 等)被拒
- 超时被 shell kill
- 超长输出落盘

Windows 适配:
- 用 Git for Windows bash(PipeShell 自动选),pwd / ls / cat 都能跑
- 不再依赖 cmd.exe,所以 pwd / ls 等 Unix 命令可用
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from taisang.agent_core.shell import PipeShell
from taisang.agent_core.tools import BashTool
from taisang.storage.paths import PathManager

_HAS_GIT = shutil.which("git") is not None


def _make_tool(tmp_path: Path, timeout: int = 10) -> tuple[BashTool, PipeShell]:
    """构造 BashTool + 持久 shell,返回 (tool, shell)。测试完要 shell.close()。"""
    shell = PipeShell(cwd=tmp_path)
    obs_dir = PathManager.observations_dir(tmp_path)
    tool = BashTool(shell=shell, observations_dir=obs_dir, timeout=timeout)
    return tool, shell


def test_bash_echo(tmp_path: Path) -> None:
    """echo hello → ok=True,output 含 hello。"""
    tool, shell = _make_tool(tmp_path)
    try:
        result = tool.run({"command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["output"]
    finally:
        shell.close()


def test_bash_empty_command(tmp_path: Path) -> None:
    """空命令 → ok=False,error 含 empty。"""
    tool, shell = _make_tool(tmp_path)
    try:
        result = tool.run({"command": ""})
        assert result["ok"] is False
        assert "empty" in result["error"]
        result_ws = tool.run({"command": "   "})
        assert result_ws["ok"] is False
        assert "empty" in result_ws["error"]
    finally:
        shell.close()


def test_bash_dangerous_command_denied(tmp_path: Path) -> None:
    """危险命令(rm -rf /)在黑名单 → ok=False,error 含 dangerous。"""
    tool, shell = _make_tool(tmp_path)
    try:
        result = tool.run({"command": "rm -rf /"})
        assert result["ok"] is False
        assert "dangerous" in result["error"]
    finally:
        shell.close()


def test_bash_cd_persists(tmp_path: Path) -> None:
    """cd 子目录后 pwd 看到新路径 — 持久 shell 的核心特性。"""
    sub = tmp_path / "subdir"
    sub.mkdir()
    tool, shell = _make_tool(tmp_path)
    try:
        # cd 到子目录
        r1 = tool.run({"command": "cd subdir"})
        assert r1["ok"] is True
        # shell cwd state 同步
        assert shell.cwd().name == "subdir"
        # pwd 验证 shell 内部 cwd 也变了
        r2 = tool.run({"command": "pwd"})
        assert r2["ok"] is True
        # pwd 输出包含 subdir(bash 路径可能是 /c/... 或 /tmp/...,但结尾是 subdir)
        assert "subdir" in r2["output"]
    finally:
        shell.close()


def test_bash_cwd_initial(tmp_path: Path) -> None:
    """初始 cwd = tmp_path。用 pwd 验证(持久 shell 用 bash,pwd 可用)。"""
    tool, shell = _make_tool(tmp_path)
    try:
        result = tool.run({"command": "pwd"})
        assert result["ok"] is True
        # bash 路径映射可能不同(/tmp/xxx 或 /c/...),但目录名 tmp_path.name 应在
        assert tmp_path.name in result["output"]
    finally:
        shell.close()


def test_bash_timeout(tmp_path: Path) -> None:
    """长跑命令被 shell timeout → ok=False,error 含 timeout。"""
    tool, shell = _make_tool(tmp_path, timeout=1)
    try:
        result = tool.run({"command": 'python -c "import time; time.sleep(5)"'})
        assert result["ok"] is False
        assert "timeout" in result["error"]
    finally:
        shell.close()


@pytest.mark.skipif(not _HAS_GIT, reason="git not available on PATH")
def test_bash_git_status(tmp_path: Path) -> None:
    """在 tmp_path 里 git init,然后 git status 跑通。"""
    import subprocess

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    tool, shell = _make_tool(tmp_path, timeout=15)
    try:
        result = tool.run({"command": "git status"})
        assert result["ok"] is True
        assert result["output"]  # 非空
    finally:
        shell.close()


def test_bash_output_persisted_when_large(tmp_path: Path) -> None:
    """合并输出 >30000 字符时落盘,output 含 persisted 包装 + preview。"""
    tool, shell = _make_tool(tmp_path, timeout=30)
    try:
        result = tool.run({"command": 'python -c "print(chr(120)*40000)"'})
        assert result["ok"] is True
        output = result["output"]
        assert "Output too large" in output
        assert "saved to" in output
        assert "Preview (first 2 KB)" in output
        assert "[/persisted-output]" in output
        persist_path = Path(result["persisted_path"])
        assert persist_path.exists()
        saved = persist_path.read_text(encoding="utf-8")
        assert len(saved) >= 40_000
    finally:
        shell.close()


def test_bash_combined_stdout_stderr(tmp_path: Path) -> None:
    """stdout + stderr 合并到一个 output 字段。"""
    tool, shell = _make_tool(tmp_path)
    try:
        script = "import sys; " "sys.stdout.write('o\\n'); " "sys.stderr.write('e\\n')"
        result = tool.run({"command": f'python -c "{script}"'})
        assert "stdout" not in result
        assert "stderr" not in result
        assert "output" in result
        assert "o" in result["output"]
        assert "e" in result["output"]
    finally:
        shell.close()
