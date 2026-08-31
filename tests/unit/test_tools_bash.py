"""Task 3:BashTool 测试。

Windows 适配说明:
- 测试只依赖 `git` / `python` / `echo` 三个跨平台稳的白名单命令。
  (git for windows 装了就有 git;项目本身是 Python 项目,python 必有;echo 是
  cmd.exe 内置命令,shell=True 下可用。)
- 不用 `ls`/`cat`/`find`/`grep`/`touch`/`mkdir`/`pwd` 这些 Unix 命令——
  Windows cmd.exe 没有它们,会报 "not recognized"。
- `git init` 测试前用 shutil.which("git") 探测,不可用就 pytest.skip。
- `test_bash_cwd_enforced` 用 `python -c "import os; print(os.getcwd())"` 而非
  `pwd`(plan 原稿写 pwd,Windows cmd.exe 无 pwd)。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from code_reader.agent_core.tools import BashTool

_HAS_GIT = shutil.which("git") is not None


def test_bash_echo(tmp_path: Path) -> None:
    """白名单内 `echo hello` → ok=True,output 含 hello。echo 是 cmd.exe 内置。"""
    tool = BashTool(source_root=tmp_path, timeout=10)
    result = tool.run({"command": "echo hello"})
    assert result["ok"] is True
    assert "hello" in result["output"]


def test_bash_empty_command(tmp_path: Path) -> None:
    """空命令 → ok=False,error 含 empty。"""
    tool = BashTool(source_root=tmp_path)
    result = tool.run({"command": ""})
    assert result["ok"] is False
    assert "empty" in result["error"]

    result_ws = tool.run({"command": "   "})
    assert result_ws["ok"] is False
    assert "empty" in result_ws["error"]


def test_bash_not_in_whitelist_denied(tmp_path: Path) -> None:
    """危险命令(rm -rf /)不在白名单前缀 → ok=False,error 含 not in whitelist。

    注意:就算误放行,subprocess 也跑不了(rm 在 Windows 不存在),但白名单
    本就该在 subprocess 之前先拒——这里只验白名单逻辑。
    """
    tool = BashTool(source_root=tmp_path)
    result = tool.run({"command": "rm -rf /"})
    assert result["ok"] is False
    assert "not in whitelist" in result["error"]


def test_bash_cwd_enforced(tmp_path: Path) -> None:
    """命令在 source_root 下跑。用 python 打印 getcwd,output 含 tmp_path。

    plan 原稿写 `pwd`,但 Windows cmd.exe 无 pwd,改用 python 等价命令。
    """
    tool = BashTool(source_root=tmp_path, timeout=10)
    result = tool.run({"command": 'python -c "import os; print(os.getcwd())"'})
    assert result["ok"] is True
    # 路径分隔符:Windows 上 getcwd 返回反斜杠,比较时统一成小写并查 tmp_path 字符串
    cwd_str = str(tmp_path)
    assert cwd_str in result["output"] or cwd_str.replace("\\", "/") in result["output"].replace(
        "\\", "/"
    )


def test_bash_timeout(tmp_path: Path) -> None:
    """长跑命令被 subprocess timeout 打断 → ok=False,error 含 timeout。

    用 `python -c "import time; time.sleep(5)"`,timeout=1。
    """
    tool = BashTool(source_root=tmp_path, timeout=1)
    result = tool.run({"command": 'python -c "import time; time.sleep(5)"'})
    assert result["ok"] is False
    assert "timeout" in result["error"]


@pytest.mark.skipif(not _HAS_GIT, reason="git not available on PATH")
def test_bash_git_status(tmp_path: Path) -> None:
    """在 tmp_path 里 `git init` 建个 repo,然后 `git status` 跑通。

    `git status` 在干净 repo 里返回 0,stdout 含分支信息或 "No commits" 之类。
    """
    import subprocess

    # 先在 tmp_path 建 git repo(直接用 subprocess,不走 BashTool,避免引入依赖)
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    tool = BashTool(source_root=tmp_path, timeout=15)
    result = tool.run({"command": "git status"})
    assert result["ok"] is True
    assert result["output"]  # 非空


def test_bash_output_persisted_when_large(tmp_path: Path) -> None:
    """合并输出 >30000 字符时落盘,output 含 persisted 包装 + preview,落盘文件存在。"""
    tool = BashTool(source_root=tmp_path, timeout=15)
    # python 打印 40000 个 x,远超 BASH_MAX_OUTPUT=30000
    result = tool.run({"command": 'python -c "print(chr(120)*40000)"'})
    assert result["ok"] is True
    output = result["output"]
    assert "Output too large" in output
    assert "saved to" in output
    assert "Preview (first 2 KB)" in output
    assert "[/persisted-output]" in output
    # 落盘文件实际存在
    persist_path = Path(result["persisted_path"])
    assert persist_path.exists()
    saved = persist_path.read_text(encoding="utf-8")
    # 落盘的是完整 40000 字符(末尾可能有换行)
    assert len(saved) >= 40_000


def test_bash_combined_stdout_stderr(tmp_path: Path) -> None:
    """stdout + stderr 合并到一个 output 字段,不再分两个键。"""
    tool = BashTool(source_root=tmp_path, timeout=10)
    # stdout 写 'o\n',stderr 写 'e\n',验证两者都进 output
    script = "import sys; " "sys.stdout.write('o\\n'); " "sys.stderr.write('e\\n')"
    result = tool.run({"command": f'python -c "{script}"'})
    assert "stdout" not in result  # 旧字段已移除
    assert "stderr" not in result
    assert "output" in result
    assert "o" in result["output"]  # stdout 的 o
    assert "e" in result["output"]  # stderr 的 e
