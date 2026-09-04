from pathlib import Path
from fastapi.testclient import TestClient
from taisang.web.app import create_app


def test_list_skills(tmp_path, monkeypatch):
    # user_dir 指向 tmp_path 避免污染真实 ~/.taisang
    user_dir = tmp_path / "skills"
    user_dir.mkdir()
    (user_dir / "commit").mkdir()
    (user_dir / "commit" / "SKILL.md").write_text(
        "---\ndescription: 生成 commit\n---\nbody", encoding="utf-8"
    )
    # 让 load_skills_config 读 tmp_path 下的 settings
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)

    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["name"] == "commit" for s in data["skills"])


def test_toggle_skill(tmp_path, monkeypatch):
    user_dir = tmp_path / "skills"
    user_dir.mkdir()
    (user_dir / "commit").mkdir()
    (user_dir / "commit" / "SKILL.md").write_text(
        "---\ndescription: d\n---\nbody", encoding="utf-8"
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    # state file 也指到 tmp_path 避免污染真实 ~/.taisang/skills_state.json
    state_file = tmp_path / "skills_state.json"
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)

    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    # 初始 disabled=False
    resp = client.get("/api/skills")
    assert next(s for s in resp.json()["skills"] if s["name"] == "commit")["disabled"] is False
    # toggle 一次 → disabled=True
    resp = client.post("/api/skills/commit/toggle")
    assert resp.status_code == 200
    assert resp.json()["disabled"] is True
    # 再 list 确认持久化
    resp = client.get("/api/skills")
    assert next(s for s in resp.json()["skills"] if s["name"] == "commit")["disabled"] is True


def test_toggle_not_found(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "skills_state.json"
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)

    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/skills/nonexistent/toggle")
    assert resp.status_code == 404


def test_reload_skills(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "skills_state.json"
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)

    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/skills/reload")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_session_registry_agent_applies_disabled_state(tmp_path, monkeypatch):
    """skills_state.json 的 disabled 状态要传导到 session_registry 建的 agent。

    toggle 只写 state 文件;若 _build_session 加载 skill 时不应用 state,
    用户在 UI 关掉的 skill 在 agent 里照样可用(bug)。
    """
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    user_dir = tmp_path / "skills"
    (user_dir / "commit").mkdir(parents=True)
    (user_dir / "commit" / "SKILL.md").write_text(
        "---\ndescription: 生成 commit\n---\nbody", encoding="utf-8"
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "skills_state.json"
    state_file.write_text('{"commit": true}', encoding="utf-8")
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)

    from taisang.web.session_registry import SessionRegistry

    reg = SessionRegistry(tmp_path)
    sess = reg.get_or_load(reg.create(title=""))
    commit = next(s for s in sess.agent.skills if s.name == "commit")
    assert commit.disabled is True
    # disabled skill 不进 system prompt 清单
    sys_msgs = [m["content"] for m in sess.agent.ctx.messages() if m["role"] == "system"]
    assert all("commit" not in c for c in sys_msgs if "可用 Skills" in c)