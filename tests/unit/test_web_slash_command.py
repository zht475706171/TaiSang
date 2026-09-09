"""测试 Web 端 slash command 触发(send_message 路由解析 /name args)。

用户 POST /api/sessions/:id/messages {query: "/name args"} →
后端渲染 command 正文 → agent.run(rendered)。
前端显示原文,后端跑渲染后版本。

用 MockLLM + TestClient,断言 LLM 收到的 message 是渲染后正文(含 command header)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from taisang.web.app import create_app


def _setup_env(monkeypatch, tmp_path):
    """配 settings + commands_state 指 tmp,建 user command 'hello'。"""
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
    (cmd_dir / "hello.md").write_text(
        "---\ndescription: 问好\n---\n请对 $ARGUMENTS 说你好",
        encoding="utf-8",
    )


def test_web_slash_command_renders(monkeypatch, tmp_path):
    """POST /messages {query: "/hello world"} → LLM 收到渲染后正文(含 $ARGUMENTS 替换)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    # 建会话
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    # 发 slash command
    resp = client.post(f"/api/sessions/{sid}/messages", json={"query": "/hello world"})
    assert resp.status_code == 200
    # 等 run 结束(同步 mock LLM 很快,但 run 在线程池,需等)
    import time
    time.sleep(0.3)
    # 读 history:agent.run 收到的是渲染后正文,第一条 user 消息应是渲染后版本
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs, "应有 user 消息"
    first_user = user_msgs[0]["content"]
    # 渲染后正文含 command header + "请对 world 说你好"
    assert "Command: hello" in first_user
    assert "请对 world 说你好" in first_user
    # 不应残留 $ARGUMENTS 字面量
    assert "$ARGUMENTS" not in first_user


def test_web_slash_command_unknown_passes_through(monkeypatch, tmp_path):
    """未知 /xxx → 当普通消息发,LLM 收到原文。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    resp = client.post(
        f"/api/sessions/{sid}/messages", json={"query": "/unknowncmd foo"}
    )
    assert resp.status_code == 200
    import time
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    # 未知 command → 原样发
    assert user_msgs[0]["content"] == "/unknowncmd foo"


def test_web_slash_command_no_args(monkeypatch, tmp_path):
    """/hello(无 args)→ $ARGUMENTS 替换为空。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    _setup_env(monkeypatch, tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    resp = client.post(f"/api/sessions/{sid}/messages", json={"query": "/hello"})
    assert resp.status_code == 200
    import time
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    assert "Command: hello" in user_msgs[0]["content"]
    # $ARGUMENTS 被替换为空
    assert "$ARGUMENTS" not in user_msgs[0]["content"]


def test_web_slash_command_disabled_not_triggered(monkeypatch, tmp_path):
    """disabled command 不触发 → 原样发。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.delenv("TAISANG_LLM_API_KEY", raising=False)
    # 先建 env,再 disable hello
    _setup_env(monkeypatch, tmp_path)
    state_file = tmp_path / "commands_state.json"
    state_file.write_text('{"hello": true}', encoding="utf-8")
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"query": "/hello world"})
    import time
    time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs
    # disabled → 原样发,不渲染
    assert user_msgs[0]["content"] == "/hello world"
    assert "Command: hello" not in user_msgs[0]["content"]