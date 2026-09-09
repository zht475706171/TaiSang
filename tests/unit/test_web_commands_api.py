"""commands_api 路由测试:list / toggle / reload / import / delete。

对齐 test_skills_api 的模式。command 是平铺 .md 文件,不是目录套 SKILL.md。
"""

from pathlib import Path
from fastapi.testclient import TestClient
from taisang.web.app import create_app


def _command_api_env(tmp_path, monkeypatch, state_json="{}"):
    """统一环境:settings 指 tmp、state 文件指 tmp、user_dirs 指 tmp/commands。

    skills 配置 user_dirs 指向 tmp/skills,commands_api._command_dirs 从 user_dirs
    派生 → tmp/commands。
    """
    skills_user_dir = tmp_path / "skills"
    skills_user_dir.mkdir(exist_ok=True)
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{skills_user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    # commands_state.json 指 tmp(避免污染真实 ~/.taisang/commands_state.json)
    state_file = tmp_path / "commands_state.json"
    state_file.write_text(state_json, encoding="utf-8")
    monkeypatch.setattr("taisang.commands.state._STATE_FILE", state_file)
    # commands_api 在模块加载时从 state 导入函数,_STATE_FILE 已 monkeypatch
    # 但 state.py 里的函数运行时读 _STATE_FILE,所以 patch state._STATE_FILE 就够了
    return tmp_path / "commands"  # 期望的 user command 目录


def test_list_commands(tmp_path, monkeypatch):
    user_dir = _command_api_env(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "foo.md").write_text(
        "---\ndescription: 测试命令\n---\n正文", encoding="utf-8"
    )
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/commands")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["commands"]]
    assert "foo" in names
    # 内置 commit/review 也应该出现(system 源)
    assert "commit" in names
    assert "review" in names


def test_list_command_fields(tmp_path, monkeypatch):
    user_dir = _command_api_env(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "foo.md").write_text(
        "---\ndescription: d\nargument-hint: <x>\nallowed-tools: Bash, read_file\n---\nbody",
        encoding="utf-8",
    )
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/commands")
    foo = next(c for c in resp.json()["commands"] if c["name"] == "foo")
    assert foo["description"] == "d"
    assert foo["argument_hint"] == "<x>"
    assert foo["allowed_tools"] == ["Bash", "read_file"]
    assert foo["source"] == "user"
    assert foo["disabled"] is False


def test_toggle_command(tmp_path, monkeypatch):
    user_dir = _command_api_env(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "foo.md").write_text("---\ndescription: d\n---\nbody", encoding="utf-8")
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    # 初始 disabled=False
    resp = client.get("/api/commands")
    foo = next(c for c in resp.json()["commands"] if c["name"] == "foo")
    assert foo["disabled"] is False
    # toggle → True
    resp = client.post("/api/commands/foo/toggle")
    assert resp.status_code == 200
    assert resp.json()["disabled"] is True
    # 再 list 确认持久化
    resp = client.get("/api/commands")
    foo = next(c for c in resp.json()["commands"] if c["name"] == "foo")
    assert foo["disabled"] is True


def test_toggle_command_not_found(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/commands/nonexistent/toggle")
    assert resp.status_code == 404


def test_reload_commands(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/commands/reload")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_import_command_md(tmp_path, monkeypatch):
    user_dir = _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: d\n---\nbody"
    resp = client.post(
        "/api/commands/import",
        files={"file": ("alpha.md", md, "text/markdown")},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "alpha"
    assert (user_dir / "alpha.md").exists()
    # list 能看到
    resp = client.get("/api/commands")
    assert any(c["name"] == "alpha" for c in resp.json()["commands"])


def test_import_command_conflict_409_then_overwrite(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: v1\n---\nv1"
    assert client.post(
        "/api/commands/import", files={"file": ("alpha.md", md, "text/markdown")}
    ).status_code == 200
    # 同名再导 → 409
    resp = client.post(
        "/api/commands/import",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 409
    # overwrite=true → 覆盖
    resp = client.post(
        "/api/commands/import?overwrite=true",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 200


def test_import_command_bad_extension(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/commands/import",
        files={"file": ("x.exe", b"bin", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_import_command_invalid_name(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    # name 含非法字符(空格)
    md = b"---\nname: bad name\ndescription: d\n---\nbody"
    resp = client.post(
        "/api/commands/import",
        files={"file": ("bad.md", md, "text/markdown")},
    )
    assert resp.status_code == 400
    assert "name" in resp.json()["detail"].lower()


def test_delete_user_command(tmp_path, monkeypatch):
    user_dir = _command_api_env(tmp_path, monkeypatch, state_json='{"alpha": true}')
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "alpha.md").write_text(
        "---\nname: alpha\ndescription: d\n---\nbody", encoding="utf-8"
    )
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/commands/alpha")
    assert resp.status_code == 200
    assert not (user_dir / "alpha.md").exists()
    # disabled 状态记录一起清掉
    import json
    state = json.loads((tmp_path / "commands_state.json").read_text(encoding="utf-8"))
    assert "alpha" not in state


def test_delete_system_command_400(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/commands/commit")  # 内置
    assert resp.status_code == 400


def test_delete_unknown_command_404(tmp_path, monkeypatch):
    _command_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/commands/nonexistent")
    assert resp.status_code == 404


def test_session_registry_agent_has_commands(tmp_path, monkeypatch):
    """_build_session 加载 commands 并传给 AgentService。

    保证 UI 管理的 command 列表和 agent 实际看到的 commands 一致。
    """
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    user_dir = _command_api_env(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "foo.md").write_text(
        "---\ndescription: d\n---\nbody", encoding="utf-8"
    )
    from taisang.web.session_registry import SessionRegistry

    reg = SessionRegistry(tmp_path)
    sess = reg.get_or_load(reg.create(title=""))
    names = [c.name for c in sess.agent.commands]
    assert "foo" in names
    # 内置 commit/review 也应该在
    assert "commit" in names
    # system prompt 里有 commands 段
    sys_msgs = [m["content"] for m in sess.agent.ctx.messages() if m["role"] == "system"]
    assert any("可用 Commands" in c for c in sys_msgs)


def test_session_registry_agent_applies_disabled_state(tmp_path, monkeypatch):
    """commands_state.json 的 disabled 状态传导到 session_registry 建的 agent。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    user_dir = _command_api_env(tmp_path, monkeypatch, state_json='{"foo": true}')
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "foo.md").write_text(
        "---\ndescription: d\n---\nbody", encoding="utf-8"
    )
    from taisang.web.session_registry import SessionRegistry

    reg = SessionRegistry(tmp_path)
    sess = reg.get_or_load(reg.create(title=""))
    foo = next(c for c in sess.agent.commands if c.name == "foo")
    assert foo.disabled is True
    # disabled command 不进 system prompt 清单
    sys_msgs = [m["content"] for m in sess.agent.ctx.messages() if m["role"] == "system"]
    commands_section = next((c for c in sys_msgs if "可用 Commands" in c), "")
    assert "/foo" not in commands_section