"""测试 CLI `chat` 子命令。

用 click.testing.CliRunner + input 参数模拟 stdin,避免真进 REPL 卡死。
覆盖:
- mock LLM 直接回答 + /exit 退出
- 无效 repo 报错退出
- --help 输出
- mock LLM 收到 query 后给出 FINAL_ANSWER
"""

from __future__ import annotations

from click.testing import CliRunner

from taisang.cli.main import cli


def test_cli_chat_with_mock_llm(monkeypatch, tmp_path):
    """mock LLM 下,启动后立即 /exit 应正常退出。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--repo", str(tmp_path)], input="/exit\n")
    assert result.exit_code == 0
    assert "taisang agent" in result.output


def test_cli_chat_invalid_repo(monkeypatch, tmp_path):
    """repo 路径不存在应 sys.exit(1) + stderr 报错。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    runner = CliRunner()
    bad = tmp_path / "nonexistent"
    result = runner.invoke(cli, ["chat", "--repo", str(bad)], input="")
    assert result.exit_code != 0
    # CliRunner 把 stderr 合进 output(mix_stderr 默认 True)
    assert "不是目录" in result.output


def test_cli_chat_help(monkeypatch):
    """`chat --help` 应打印 docstring,不进 REPL。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"], input="")
    assert result.exit_code == 0
    assert "进入交互式 coding agent" in result.output


def test_cli_chat_mock_query_then_exit(monkeypatch, tmp_path):
    """mock LLM:输入 query 拿到 mock 回答,再 /exit 退出。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--repo", str(tmp_path)], input="你好\n/exit\n")
    assert result.exit_code == 0
    # mock LLM 直接返回答案(FINAL_ANSWER),答案文本应在 stdout
    assert "mock" in result.output
