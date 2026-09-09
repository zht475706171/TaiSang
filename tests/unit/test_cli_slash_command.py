"""测试 CLI slash command 触发。

用户输入 /name args → CLI 查 CommandRegistry → 命中则 agent.run(rendered)。
不命中则当普通消息发。

用 click.testing.CliRunner + input 模拟 stdin。
"""

from __future__ import annotations

from click.testing import CliRunner

from taisang.cli.main import cli


def _setup_commands_env(monkeypatch, tmp_path):
    """配 settings + commands_state 指 tmp,避免污染真实 ~/.taisang。"""
    skills_user_dir = tmp_path / "skills"
    skills_user_dir.mkdir(exist_ok=True)
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{skills_user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "commands_state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("taisang.commands.state._STATE_FILE", state_file)
    # 建 user command
    cmd_dir = tmp_path / "commands"
    cmd_dir.mkdir(exist_ok=True)
    (cmd_dir / "hello.md").write_text(
        "---\ndescription: 问好\nargument-hint: <name>\n---\n请用热情语气对 $ARGUMENTS 说你好",
        encoding="utf-8",
    )


def test_cli_slash_command_triggers(monkeypatch, tmp_path):
    """/hello world → CLI 渲染 command 正文 → agent.run(渲染后版本)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_commands_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["chat", "--repo", str(tmp_path)], input="/hello world\n/exit\n"
    )
    assert result.exit_code == 0
    # 执行 command 的提示语出现
    assert "执行 command" in result.output
    assert "/hello world" in result.output


def test_cli_slash_command_unknown_falls_through(monkeypatch, tmp_path):
    """未知 /xxx → 当普通消息发给 LLM(不报错,不命中)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_commands_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["chat", "--repo", str(tmp_path)], input="/unknowncmd extra\n/exit\n"
    )
    assert result.exit_code == 0
    # 未知 command 不打印"执行 command"提示
    assert "执行 command" not in result.output


def test_cli_slash_command_no_args(monkeypatch, tmp_path):
    """/hello(无 args)→ 渲染时 $ARGUMENTS 替换为空字符串。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_commands_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["chat", "--repo", str(tmp_path)], input="/hello\n/exit\n"
    )
    assert result.exit_code == 0
    assert "执行 command" in result.output


def test_cli_builtin_command_still_works(monkeypatch, tmp_path):
    """/reset /debug /exit 仍走内置分支,不被 command 拦截。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_commands_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["chat", "--repo", str(tmp_path)], input="/debug\n/reset\n/exit\n"
    )
    assert result.exit_code == 0
    assert "debug ON" in result.output
    assert "上下文已重置" in result.output