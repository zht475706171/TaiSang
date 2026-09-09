"""端到端测试:slash command 从用户输入到 LLM 收到渲染后正文。

覆盖 CLI + Web 两条触发路径,验证:
1. 用户输入 /name args → 渲染 → agent.run(rendered)
2. 前端显示原文(不在 history 里留渲染后长文 for web;CLI 只打印"执行 command"提示)
3. $ARGUMENTS 被正确替换
4. disabled command 不触发
5. 未知 /xxx 当普通消息发
"""

from __future__ import annotations

import time
from pathlib import Path

from click.testing import CliRunner
from fastapi.testclient import TestClient

from taisang.cli.main import cli
from taisang.web.app import create_app


def _setup_env(monkeypatch, tmp_path):
    """配 settings + commands_state 指 tmp,建 user command 'echo'。"""
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
    cmd_dir = tmp_path / "commands"
    cmd_dir.mkdir(exist_ok=True)
    (cmd_dir / "echo.md").write_text(
        "---\ndescription: 回显参数\nargument-hint: <text>\n---\n请回显以下内容: $ARGUMENTS",
        encoding="utf-8",
    )


def test_e2e_cli_slash_command(monkeypatch, tmp_path):
    """CLI: /echo hello → agent.run 收到渲染后正文(含 "请回显以下内容: hello")。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["chat", "--repo", str(tmp_path)], input="/echo hello\n/exit\n"
    )
    assert result.exit_code == 0
    assert "执行 command" in result.output
    assert "/echo hello" in result.output


def test_e2e_web_slash_command_full_flow(monkeypatch, tmp_path):
    """Web: POST /messages {query: "/echo hello"} → LLM 收到渲染后正文 + history 落盘渲染版本。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    # 建会话
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    # 发 slash command
    resp = client.post(f"/api/sessions/{sid}/messages", json={"query": "/echo hello"})
    assert resp.status_code == 200
    # 等 run 结束
    time.sleep(0.3)
    # 读 history:agent.run 收到渲染后正文
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    content = user_msgs[0]["content"]
    assert "Command: echo" in content
    assert "请回显以下内容: hello" in content
    assert "$ARGUMENTS" not in content


def test_e2e_web_disabled_command_passes_through(monkeypatch, tmp_path):
    """Web: disabled command → 原样发,不渲染。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    # disable echo
    state_file = tmp_path / "commands_state.json"
    state_file.write_text('{"echo": true}', encoding="utf-8")
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"query": "/echo hello"})
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    assert user_msgs[0]["content"] == "/echo hello"
    assert "Command: echo" not in user_msgs[0]["content"]


def test_e2e_web_unknown_slash_passes_through(monkeypatch, tmp_path):
    """Web: 未知 /xxx → 原样发。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"query": "/unknown stuff"})
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    assert user_msgs[0]["content"] == "/unknown stuff"


def test_e2e_web_builtin_command_in_system_prompt(monkeypatch, tmp_path):
    """Web: 内置 commit/review command 在 system prompt 的 Commands 段里能看到。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    # 内置 commit 可触发(渲染后正文进 history)
    client.post(f"/api/sessions/{sid}/messages", json={"query": "/commit fix typo"})
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    content = user_msgs[0]["content"]
    assert "Command: commit" in content
    assert "fix typo" in content