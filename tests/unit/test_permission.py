"""PermissionManager 测试。

覆盖:
- _find_project_root:找 .git / fallback home / fallback 盘符第一级
- check:已批准放行 / 未批准问用户 / 批准后缓存
- CliPermissionManager:stdin y/n(模拟)
- AutoApprove / AutoDeny:测试用适配器
- WebPermissionManager:token + Event + resolve(同 WebConfirmer 模式)
"""

from __future__ import annotations

import threading
from pathlib import Path

from taisang.agent_core.permission import (
    AutoApprovePermissionManager,
    AutoDenyPermissionManager,
    CliPermissionManager,
    WebPermissionManager,
    _find_project_root,
)

# -------------------- _find_project_root --------------------


def test_find_project_root_with_git(tmp_path: Path) -> None:
    """路径所在目录有 .git → 返回该目录。"""
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert _find_project_root(sub, home=Path("/nonexistent")) == tmp_path.resolve()


def test_find_project_root_fallback_first_level(tmp_path: Path) -> None:
    """无 .git 且不在 home 内 → 返回盘符后第一级(Windows)或根后第一级(Unix)。

    tmp_path 在 home 内时会 fallback 到 home,所以用一个明确不在 home 内的路径。
    """
    # 用一个明确不在 home 内的路径(Windows: D:/something)
    fake_path = Path("D:/GoProject/some-repo/src/cmd")
    root = _find_project_root(fake_path, home=Path("C:/Users/someone"))
    # Windows: D:/GoProject/some-repo (parts[:3])
    # Unix: /GoProject/some-repo (parts[:2]) — 但 D: 是 Windows 盘符
    parts = Path("D:/GoProject/some-repo/src/cmd").resolve().parts
    if len(parts) >= 3:
        assert root == Path(*parts[:3])


def test_find_project_root_inside_home(tmp_path: Path) -> None:
    """路径在 home 内 → 返回 home(home 默认已批准,不问)。"""
    home = tmp_path  # 用 tmp_path 当 home
    target = home / "projects" / "repo"
    target.mkdir(parents=True)
    assert _find_project_root(target, home=home) == home.resolve()


# -------------------- AutoApprove / AutoDeny --------------------


def test_auto_approve_allows_anything(tmp_path: Path) -> None:
    """AutoApprove 无脑批准所有路径。"""
    perm = AutoApprovePermissionManager(initial_dirs=[])
    assert perm.check(tmp_path / "anywhere") is True
    assert perm.check(Path("D:/some/random/path")) is True


def test_auto_deny_rejects_new(tmp_path: Path) -> None:
    """AutoDeny 对已批准目录放行,新目录拒。"""
    perm = AutoDenyPermissionManager(initial_dirs=[tmp_path])
    # tmp_path 在已批准 → 放行
    assert perm.check(tmp_path / "subdir") is True
    # 外部目录 → 拒
    assert perm.check(Path("D:/other/random")) is False


def test_initial_dirs_approved_directly(tmp_path: Path) -> None:
    """initial_dirs 直接批准路径本身,不走 _find_project_root。

    防止 --repo D:/proj(proj 在 home 内)把整个 home 批准。
    """
    # tmp_path 在 home 内,但 initial_dirs 只批准 tmp_path 本身
    perm = AutoDenyPermissionManager(initial_dirs=[tmp_path], home=Path.home())
    # tmp_path 内 → 放行(已批准)
    assert perm.check(tmp_path / "file.py") is True
    # tmp_path 外但仍在 home 内 → 拒(home 没被批准)
    other = Path.home() / "other-project"
    assert perm.check(other) is False


def test_approved_dirs_returns_sorted(tmp_path: Path) -> None:
    """approved_dirs() 返回已批准列表(排序)。"""
    perm = AutoApprovePermissionManager(initial_dirs=[tmp_path])
    dirs = perm.approved_dirs()
    assert tmp_path.resolve() in dirs


# -------------------- CliPermissionManager --------------------


def test_cli_permission_approve(monkeypatch, tmp_path: Path) -> None:
    """stdin 输入 y → 批准,加入已批准集合,后续不问。"""
    inputs = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))
    # 抑制 print
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

    perm = CliPermissionManager(initial_dirs=[])
    target = tmp_path / "new-project"
    target.mkdir()
    assert perm.check(target) is True
    # 第二次不问(已批准)
    assert perm.check(target) is True


def test_cli_permission_deny(monkeypatch, tmp_path: Path) -> None:
    """stdin 输入 n → 拒绝,不加入已批准。"""
    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

    perm = CliPermissionManager(initial_dirs=[])
    target = tmp_path / "denied-project"
    target.mkdir()
    assert perm.check(target) is False


def test_cli_permission_eof_denies(monkeypatch) -> None:
    """stdin EOF(Ctrl+D) → 默认拒。"""

    def _raise_eof(*a, **kw):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

    perm = CliPermissionManager(initial_dirs=[])
    assert perm.check(Path("D:/anywhere")) is False


# -------------------- WebPermissionManager --------------------


def test_web_permission_approve_after_resolve(tmp_path: Path) -> None:
    """WebPermissionManager:emit 事件 → resolve(approve) → check 返回 True。"""
    emitted: list[tuple[str, dict]] = []

    def emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    perm = WebPermissionManager(emit=emit, initial_dirs=[], timeout=2.0)
    target = tmp_path / "web-project"
    target.mkdir()

    # 在另一个线程跑 check(它会阻塞等 resolve)
    result_holder: dict = {}

    def _check():
        result_holder["ok"] = perm.check(target)

    t = threading.Thread(target=_check)
    t.start()

    # 等 emit 出 permission_request 事件
    import time

    while not emitted:
        time.sleep(0.01)

    event_type, payload = emitted[-1]
    assert event_type == "permission_request"
    token = payload["token"]
    # permission_request 问的是 project root(target 在 home 内 → root=home)
    # 而非 target 本身。批准 project root 后该 root 内所有子目录都不问。
    from taisang.agent_core.permission import _find_project_root

    expected_root = _find_project_root(target, home=Path.home())
    assert payload["path"] == str(expected_root.resolve())

    # 模拟前端 POST resolve
    ok = perm.resolve(token, approve=True)
    assert ok is True

    t.join(timeout=2)
    assert result_holder["ok"] is True

    # 第二次不问(已批准)
    emitted.clear()
    assert perm.check(target) is True
    assert emitted == []  # 没 emit 新事件


def test_web_permission_deny_after_resolve(tmp_path: Path) -> None:
    """WebPermissionManager:resolve(approve=False) → check 返回 False。"""
    emitted: list[tuple[str, dict]] = []

    def emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    perm = WebPermissionManager(emit=emit, initial_dirs=[], timeout=2.0)
    target = tmp_path / "denied-web"
    target.mkdir()

    result_holder: dict = {}

    def _check():
        result_holder["ok"] = perm.check(target)

    t = threading.Thread(target=_check)
    t.start()

    import time

    while not emitted:
        time.sleep(0.01)

    token = emitted[-1][1]["token"]
    perm.resolve(token, approve=False)

    t.join(timeout=2)
    assert result_holder["ok"] is False


def test_web_permission_timeout_denies(tmp_path: Path) -> None:
    """WebPermissionManager:超时无 resolve → 默认拒(False)。"""
    emitted: list[tuple[str, dict]] = []

    def emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    # 超短 timeout(0.3s),不调 resolve → 超时拒
    perm = WebPermissionManager(emit=emit, initial_dirs=[], timeout=0.3)
    target = tmp_path / "timeout-web"
    target.mkdir()

    assert perm.check(target) is False
    assert len(emitted) == 1  # 发过一次 permission_request


def test_web_permission_resolve_invalid_token(tmp_path: Path) -> None:
    """resolve 用无效 token → 返回 False(不崩)。"""
    emitted: list[tuple[str, dict]] = []

    def emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    perm = WebPermissionManager(emit=emit, initial_dirs=[], timeout=1.0)
    # 没有任何 pending,resolve 假 token → False
    assert perm.resolve("nonexistent-token", approve=True) is False


def test_web_permission_initial_dirs_approved(tmp_path: Path) -> None:
    """WebPermissionManager 的 initial_dirs 也直接批准,不问。"""
    emitted: list[tuple[str, dict]] = []

    def emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    perm = WebPermissionManager(emit=emit, initial_dirs=[tmp_path], timeout=1.0)
    # tmp_path 内不问
    assert perm.check(tmp_path / "subdir") is True
    assert emitted == []
