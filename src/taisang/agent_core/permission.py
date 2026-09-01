"""目录访问权限管理:首次访问新目录时问用户批准。

模型(类 Claude Code permission):
- PermissionManager 跟踪已批准目录列表 approved_dirs
- agent 访问某路径,解析出其"项目根"(路径所在的有 .git 的目录,或路径本身)
  - 若项目根在 approved_dirs 内 → 放行
  - 否则触发 ask(path) 回调,问用户
    - 用户批准 → 项目根加入 approved_dirs,后续该目录内访问不再问
    - 用户拒绝 → 返回 False,工具报 permission denied

触发点:
- Bash cd 切到新目录
- 文件工具(Read/Grep/Glob/Edit/Write)解析路径后

CLI:stdin y/n(default_permission_ask)
Web:经 SSE permission_request 事件,前端弹卡片,POST /permission/{token} resolve
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _find_project_root(path: Path, home: Path | None = None) -> Path:
    """从 path 往上找,直到含 .git 的目录;找不到就返回 path 所在顶层(家目录外第一级)。

    策略:
    1. 从 path.resolve() 往上找 .git,找到 → 该目录是项目根
    2. 找不到 .git → 取家目录外的第一级目录
       (如 D:/GoProject/tendering-custom/cmd → D:/GoProject/tendering-custom)
    3. 路径在家目录内 → 返回家目录(家目录本身已批准,不问)
    """
    resolved = path.resolve()
    # 1. 找 .git
    cur = resolved
    for _ in range(20):  # 最多向上 20 级,防无限循环
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    # 2. 家目录外第一级
    if home is not None:
        home_resolved = home.resolve()
        try:
            rel = resolved.relative_to(home_resolved)
            # 在家目录内 → 返回家目录(已默认批准)
            if not rel.parts:
                return home_resolved
            return home_resolved
        except ValueError:
            pass
    # 3. 非 Windows 盘符路径:取根后第一级
    # Windows: D:/GoProject/tendering-custom/cmd → D:/GoProject/tendering-custom
    parts = resolved.parts
    if len(parts) >= 3:
        return Path(*parts[:3])
    if len(parts) >= 1:
        return Path(*parts)
    return resolved


class PermissionManager:
    """权限管理抽象基类。子类实现 _ask(path) -> bool。"""

    def __init__(self, initial_dirs: list[Path], home: Path | None = None) -> None:
        self._approved: set[Path] = set()
        self._lock = threading.Lock()
        self._home = home
        # initial_dirs 直接批准路径本身(不走 _find_project_root)。
        # 否则传 --repo D:/proj 会把 home 整个批准(若 proj 在 home 内)。
        for d in initial_dirs:
            with self._lock:
                self._approved.add(d.resolve())

    def _approve(self, path: Path) -> None:
        """把路径的项目根加入已批准集合。"""
        root = _find_project_root(path, self._home)
        with self._lock:
            self._approved.add(root.resolve())

    def check(self, path: Path) -> bool:
        """检查 path 是否可访问。已批准 → True;否则调 _ask 问用户。

        返回 True 表示可访问;False 表示用户拒绝。
        递归:用户批准后,该目录内后续访问不再问。

        两层检查:
        1. path 本身是否落在某已批准目录内(含子目录) → 直接放行
        2. 否则算 path 的 project root,看 project root 是否已批准;
           未批准则问用户是否批准该 project root
        """
        try:
            path_resolved = path.resolve()
        except (OSError, ValueError):
            return False
        with self._lock:
            # 层 1:path 本身在已批准目录内 → 放行
            for d in self._approved:
                try:
                    path_resolved.relative_to(d)
                    return True
                except ValueError:
                    continue
        # 层 2:算 project root,问用户
        root = _find_project_root(path, self._home)
        root_resolved = root.resolve()
        with self._lock:
            if root_resolved in self._approved:
                return True
        ok = self._ask(root_resolved)
        if ok:
            with self._lock:
                self._approved.add(root_resolved)
        return ok

    def _ask(self, path: Path) -> bool:
        """子类实现:问用户是否批准 path。返回 True/False。"""
        raise NotImplementedError

    def approved_dirs(self) -> list[Path]:
        """返回已批准目录列表(调试/展示用)。"""
        with self._lock:
            return sorted(self._approved)


class CliPermissionManager(PermissionManager):
    """CLI 版:stdin y/n 问用户。"""

    def _ask(self, path: Path) -> bool:
        print(f"\n[PERMISSION] agent wants to access: {path}")
        try:
            ans = input("  allow? (y/N): ").strip().lower()
            return ans == "y"
        except (EOFError, KeyboardInterrupt):
            return False


class AutoApprovePermissionManager(PermissionManager):
    """测试用:无脑批准所有目录。"""

    def _ask(self, path: Path) -> bool:
        return True


class AutoDenyPermissionManager(PermissionManager):
    """测试用:无脑拒绝所有新目录(已批准的仍放行)。"""

    def _ask(self, path: Path) -> bool:
        return False


class WebPermissionManager(PermissionManager):
    """Web UI 版:经 SSE permission_request 事件问用户,前端 POST resolve。

    机制同 WebConfirmer:
    1. _ask 生成 token,emit permission_request 事件
    2. 阻塞 threading.Event.wait(timeout)
    3. 前端弹卡片,POST /api/sessions/{id}/permission/{token} {approve: bool}
    4. 端点调 resolve(token, approve),set event
    5. _ask 返回 approve;超时默认 deny
    """

    def __init__(
        self,
        emit: Callable[[str, dict[str, Any]], None],
        initial_dirs: list[Path],
        home: Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(initial_dirs, home)
        self._emit = emit
        self._timeout = timeout
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}

    def _ask(self, path: Path) -> bool:
        token = uuid.uuid4().hex[:12]
        evt = threading.Event()
        with self._lock:
            self._pending[token] = evt
        self._emit(
            "permission_request",
            {"token": token, "path": str(path)},
        )
        ok = evt.wait(timeout=self._timeout)
        with self._lock:
            self._pending.pop(token, None)
            result = self._results.pop(token, False)
        return ok and result

    def resolve(self, token: str, approve: bool) -> bool:
        """前端 POST 确认结果时调用。返回 True 表示 token 有效已处理。"""
        with self._lock:
            evt = self._pending.get(token)
            if evt is None:
                return False
            self._results[token] = approve
        evt.set()
        return True
