from pathlib import Path
from fastapi.testclient import TestClient
from taisang.web.app import create_app


def _skill_api_env(tmp_path, monkeypatch, state_json="{}"):
    """统一环境:settings 指 tmp、state 文件指 tmp、user_dirs 指 tmp/skills。"""
    user_dir = tmp_path / "skills"
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "skills_state.json"
    state_file.write_text(state_json, encoding="utf-8")
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)
    return user_dir


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


def test_import_md_via_api(tmp_path, monkeypatch):
    user_dir = _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: d\n---\nbody"
    resp = client.post(
        "/api/skills/import", files={"file": ("alpha.md", md, "text/markdown")}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "alpha"
    assert (user_dir / "alpha" / "SKILL.md").exists()
    # list 里能看到
    resp = client.get("/api/skills")
    assert any(s["name"] == "alpha" for s in resp.json()["skills"])


def test_import_md_conflict_409_then_overwrite(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: v1\n---\nv1"
    assert client.post(
        "/api/skills/import", files={"file": ("alpha.md", md, "text/markdown")}
    ).status_code == 200
    # 同名再导 → 409
    resp = client.post(
        "/api/skills/import",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 409
    # overwrite=true → 覆盖成功
    resp = client.post(
        "/api/skills/import?overwrite=true",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 200


def test_import_bad_extension_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/skills/import", files={"file": ("x.exe", b"bin", "application/octet-stream")}
    )
    assert resp.status_code == 400


def test_import_md_missing_name_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/skills/import", files={"file": ("a.md", b"no frontmatter", "text/markdown")}
    )
    assert resp.status_code == 400
    assert "frontmatter" in resp.json()["detail"]


def test_delete_user_skill(tmp_path, monkeypatch):
    user_dir = _skill_api_env(tmp_path, monkeypatch, state_json='{"alpha": true}')
    (user_dir / "alpha").mkdir(parents=True)
    (user_dir / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: d\n---\nbody", encoding="utf-8"
    )
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/alpha")
    assert resp.status_code == 200
    assert not (user_dir / "alpha").exists()
    # disabled 状态记录一起清掉(重导入同名不会莫名 disabled)
    import json
    state = json.loads((tmp_path / "skills_state.json").read_text(encoding="utf-8"))
    assert "alpha" not in state


def test_delete_system_skill_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/commit")  # 内置
    assert resp.status_code == 400


def test_delete_unknown_404(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/nonexistent")
    assert resp.status_code == 404


# ---------- Plugin API ----------
import subprocess
from unittest.mock import patch


def _make_superpowers_fixture(tmp_path) -> Path:
    root = tmp_path / "fixture"
    (root / "skills" / "brainstorming").mkdir(parents=True)
    (root / "skills" / "brainstorming" / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: d\n---\nbody", encoding="utf-8"
    )
    (root / "skills" / "writing-plans").mkdir(parents=True)
    (root / "skills" / "writing-plans" / "SKILL.md").write_text(
        "---\nname: writing-plans\ndescription: d2\n---\nbody2", encoding="utf-8"
    )
    (root / "package.json").write_text('{"version": "5.1.0"}', encoding="utf-8")
    return root


def _fake_clone_factory(fixture_root: Path):
    def _fake(cmd, *a, **kw):
        target = Path(cmd[3])
        target.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(fixture_root, target, dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    return _fake


def _plugin_api_env(tmp_path, monkeypatch):
    """和 _skill_api_env 一样,但额外把 plugins_file 指到 tmp。"""
    user_dir = _skill_api_env(tmp_path, monkeypatch)
    plugins_file = tmp_path / "installed_plugins.json"
    monkeypatch.setattr("taisang.web.skills_api._PLUGINS_FILE", plugins_file)
    return user_dir, plugins_file


def test_install_plugin_api_success(tmp_path, monkeypatch):
    user_dir, plugins_file = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123def456\n"):
            resp = client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plugin"] == "superpowers"
    assert data["version"] == "5.1.0"
    assert "brainstorming" in data["skills"]
    # 落盘
    assert (user_dir / "superpowers" / "brainstorming" / "SKILL.md").exists()


def test_install_plugin_api_invalid_source_400(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/skills/install-plugin", json={"source": "not-a-url"})
    assert resp.status_code == 400
    assert "格式" in resp.json()["detail"] or "地址" in resp.json()["detail"]


def test_install_plugin_api_clone_failure_400(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    def _fail(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: not found")
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fail):
        resp = client.post("/api/skills/install-plugin", json={"source": "nobody/nope"})
    assert resp.status_code == 400
    assert "git clone" in resp.json()["detail"]


def test_list_plugins_api_empty(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/skills/plugins")
    assert resp.status_code == 200
    assert resp.json() == {"plugins": []}


def test_list_plugins_api_after_install(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.get("/api/skills/plugins")
    data = resp.json()
    assert len(data["plugins"]) == 1
    p = data["plugins"][0]
    assert p["name"] == "superpowers"
    assert p["version"] == "5.1.0"
    assert "brainstorming" in p["skills"]


def test_uninstall_plugin_api_success(tmp_path, monkeypatch):
    user_dir, plugins_file = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.delete("/api/skills/plugin/superpowers")
    assert resp.status_code == 200
    assert not (user_dir / "superpowers").exists()
    # 再 list 应空
    resp = client.get("/api/skills/plugins")
    assert resp.json() == {"plugins": []}


def test_uninstall_plugin_api_missing_404(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/plugin/nonexistent")
    assert resp.status_code == 404


def test_list_skills_returns_plugin_name(tmp_path, monkeypatch):
    user_dir, _ = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.get("/api/skills")
    skills = resp.json()["skills"]
    bp = next(s for s in skills if s["name"] == "brainstorming")
    assert bp["plugin_name"] == "superpowers"
    # 非 plugin skill 的 plugin_name 为 None
    if any(s["name"] == "commit" for s in skills):
        commit = next(s for s in skills if s["name"] == "commit")
        assert commit["plugin_name"] is None