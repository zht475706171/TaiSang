"""--dangerously-skip-permissions(免确认模式)单元测试。

测试 bypass_enabled=True 时:
1. PermissionManager.check() 直接放行所有路径
2. BypassableConfirmer 直接放行
3. BashTool 跳过危险命令黑名单
4. 运行时切换 bypass_enabled 后立即生效
5. bypass_enabled=False 时原有行为不变
6. AgentService(skip_permissions=True) 正确设 bypass_enabled
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from taisang.agent_core.confirm import (
    AutoApproveConfirmer,
    AutoDenyConfirmer,
    BypassableConfirmer,
    default_confirmer,
)
from taisang.agent_core.permission import (
    AutoApprovePermissionManager,
    AutoDenyPermissionManager,
    CliPermissionManager,
    PermissionManager,
)


class TestPermissionManagerBypass:
    """PermissionManager.bypass_enabled 测试。"""

    def test_bypass_default_false(self, tmp_path: Path) -> None:
        """新建 manager 时 bypass_enabled 默认 False。"""
        pm = CliPermissionManager(initial_dirs=[tmp_path])
        assert pm.bypass_enabled is False

    def test_bypass_true_check_always_passes(self, tmp_path: Path) -> None:
        """bypass_enabled=True 时 check() 对任意路径返回 True。"""
        pm = AutoDenyPermissionManager(initial_dirs=[])
        # AutoDeny 的 _ask 返回 False,正常情况下 check 新目录会拒绝
        pm.bypass_enabled = True
        # 访问一个完全不在 approved 里的路径
        random_path = Path("C:/nonexistent/random/path")
        assert pm.check(random_path) is True

    def test_bypass_false_normal_behavior(self, tmp_path: Path) -> None:
        """bypass_enabled=False 时 AutoDeny 仍然拒绝新目录。"""
        pm = AutoDenyPermissionManager(initial_dirs=[])
        pm.bypass_enabled = False
        random_path = Path("C:/nonexistent/random/path")
        assert pm.check(random_path) is False

    def test_bypass_runtime_toggle(self, tmp_path: Path) -> None:
        """运行时翻转 bypass_enabled 后立即生效。"""
        pm = AutoDenyPermissionManager(initial_dirs=[])
        random_path = Path("C:/nonexistent/random/path")

        # 先关闭:拒绝
        pm.bypass_enabled = False
        assert pm.check(random_path) is False

        # 开启:放行
        pm.bypass_enabled = True
        assert pm.check(random_path) is True

        # 再关闭:又拒绝
        pm.bypass_enabled = False
        assert pm.check(random_path) is False


class TestBypassableConfirmer:
    """BypassableConfirmer 测试。"""

    def test_bypass_true_directly_approves(self) -> None:
        """bypass_getter 返回 True 时直接放行,不调 inner。"""
        inner = MagicMock(return_value=False)  # inner 返回 False
        confirmer = BypassableConfirmer(inner, bypass_getter=lambda: True)
        assert confirmer("/some/file.py", "old", "new") is True
        inner.assert_not_called()  # inner 没被调

    def test_bypass_false_delegates_to_inner(self) -> None:
        """bypass_getter 返回 False 时走 inner confirmer。"""
        inner = MagicMock(return_value=True)
        confirmer = BypassableConfirmer(inner, bypass_getter=lambda: False)
        assert confirmer("/some/file.py", "old", "new") is True
        inner.assert_called_once_with("/some/file.py", "old", "new")

    def test_bypass_runtime_toggle(self) -> None:
        """运行时翻转 bypass 后 confirmer 行为跟着变。"""
        state = {"bypass": False}
        inner = MagicMock(return_value=False)
        confirmer = BypassableConfirmer(inner, bypass_getter=lambda: state["bypass"])

        # bypass 关:走 inner,返回 False
        assert confirmer("/f.py", "", "x") is False
        inner.assert_called_once()

        # bypass 开:直接放行
        state["bypass"] = True
        inner.reset_mock()
        assert confirmer("/f.py", "", "x") is True
        inner.assert_not_called()


class TestBashToolBypass:
    """BashTool 危险命令检查在 bypass 时跳过。"""

    def _make_bash_tool(self, tmp_path: Path, bypass: bool = False):
        from taisang.agent_core.permission import AutoApprovePermissionManager
        from taisang.agent_core.shell import PipeShell
        from taisang.agent_core.tools import BashTool

        pm = AutoApprovePermissionManager(initial_dirs=[tmp_path])
        pm.bypass_enabled = bypass
        shell = PipeShell(cwd=tmp_path)
        return BashTool(shell=shell, observations_dir=tmp_path / ".obs", permission=pm)

    def test_bypass_false_blocks_dangerous(self, tmp_path: Path) -> None:
        """bypass=False 时危险命令被拦。"""
        tool = self._make_bash_tool(tmp_path, bypass=False)
        result = tool.run({"command": "rm -rf /"})
        assert result["ok"] is False
        assert "dangerous command blocked" in result["error"]

    def test_bypass_true_allows_dangerous(self, tmp_path: Path) -> None:
        """bypass=True 时危险命令不被拦(通过黑名单检查)。

        注意:命令可能因其他原因失败(如 rm -rf / 需要 root),
        但不应该被 "dangerous command blocked" 拦截。
        """
        tool = self._make_bash_tool(tmp_path, bypass=True)
        result = tool.run({"command": "echo hello"})
        # echo 是安全命令,应该成功执行
        assert result["ok"] is True

    def test_bypass_true_skips_dangerous_check(self, tmp_path: Path) -> None:
        """bypass=True 时危险命令不返回 'dangerous command blocked' 错误。"""
        tool = self._make_bash_tool(tmp_path, bypass=True)
        # rm -rf / 会通过黑名单检查,但实际执行可能失败(权限不足等)
        result = tool.run({"command": "rm -rf /nonexistent_skip_test_dir_xyz"})
        # 不应该被 "dangerous command blocked" 拦
        if not result["ok"]:
            assert "dangerous command blocked" not in result["error"]


class TestAgentServiceSkipPermissions:
    """AgentService(skip_permissions=True) 集成测试。"""

    def test_skip_permissions_sets_bypass(self, tmp_path: Path) -> None:
        """AgentService(skip_permissions=True) 时 permission.bypass_enabled=True。"""
        from taisang.agent_core.permission import CliPermissionManager
        from taisang.agent_core.service import AgentService
        from taisang.llm_client import MockLLM, LLMResponse

        llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
        pm = CliPermissionManager(initial_dirs=[tmp_path])
        agent = AgentService(
            llm=llm,
            source_root=tmp_path,
            confirmer=default_confirmer,
            permission=pm,
            skip_permissions=True,
        )
        assert agent.permission.bypass_enabled is True

    def test_no_skip_permissions_bypass_false(self, tmp_path: Path) -> None:
        """AgentService(skip_permissions=False) 时 permission.bypass_enabled=False。"""
        from taisang.agent_core.permission import CliPermissionManager
        from taisang.agent_core.service import AgentService
        from taisang.llm_client import MockLLM, LLMResponse

        llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
        pm = CliPermissionManager(initial_dirs=[tmp_path])
        agent = AgentService(
            llm=llm,
            source_root=tmp_path,
            confirmer=default_confirmer,
            permission=pm,
            skip_permissions=False,
        )
        assert agent.permission.bypass_enabled is False

    def test_confirmer_wrapped_with_bypass(self, tmp_path: Path) -> None:
        """AgentService 的 confirmer 是 BypassableConfirmer,感知 bypass_enabled。"""
        from taisang.agent_core.confirm import BypassableConfirmer
        from taisang.agent_core.permission import CliPermissionManager
        from taisang.agent_core.service import AgentService
        from taisang.llm_client import MockLLM, LLMResponse

        llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
        pm = CliPermissionManager(initial_dirs=[tmp_path])
        agent = AgentService(
            llm=llm,
            source_root=tmp_path,
            confirmer=AutoDenyConfirmer(),
            permission=pm,
            skip_permissions=True,
        )
        # confirmer 应该是 BypassableConfirmer
        assert isinstance(agent.confirmer, BypassableConfirmer)
        # bypass=True 时即使 inner 是 AutoDenyConfirmer,也返回 True
        assert agent.confirmer("/f.py", "old", "new") is True

    def test_runtime_toggle_reflected_in_confirmer(self, tmp_path: Path) -> None:
        """运行时翻转 bypass_enabled 后 confirmer 行为跟着变。"""
        from taisang.agent_core.permission import CliPermissionManager
        from taisang.agent_core.service import AgentService
        from taisang.llm_client import MockLLM, LLMResponse

        llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
        pm = CliPermissionManager(initial_dirs=[tmp_path])
        agent = AgentService(
            llm=llm,
            source_root=tmp_path,
            confirmer=AutoDenyConfirmer(),
            permission=pm,
            skip_permissions=False,
        )
        # bypass=False:走 inner(AutoDeny),返回 False
        assert agent.confirmer("/f.py", "old", "new") is False

        # 运行时翻转
        agent.permission.bypass_enabled = True
        # bypass=True:直接放行
        assert agent.confirmer("/f.py", "old", "new") is True


class TestConfigSkipPermissions:
    """config.py 的 skip_permissions 读写测试。"""

    def test_load_default_false(self, tmp_path: Path, monkeypatch) -> None:
        """settings.json 不存在时 load_skip_permissions 返回 False。"""
        import taisang.config as config_module

        monkeypatch.setattr(config_module, "_settings_path", lambda: tmp_path / "noexist.json")
        assert config_module.load_skip_permissions() is False

    def test_save_then_load(self, tmp_path: Path, monkeypatch) -> None:
        """save → load 往返正确。"""
        import taisang.config as config_module

        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(config_module, "_settings_path", lambda: settings_file)

        config_module.save_skip_permissions(True)
        assert config_module.load_skip_permissions() is True

        config_module.save_skip_permissions(False)
        assert config_module.load_skip_permissions() is False

    def test_save_preserves_other_fields(self, tmp_path: Path, monkeypatch) -> None:
        """save_skip_permissions 不覆盖 settings.json 里其他字段。"""
        import json
        import taisang.config as config_module

        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(config_module, "_settings_path", lambda: settings_file)

        # 先写一个有其他字段的 settings.json
        settings_file.write_text(
            json.dumps({"llm": {"model": "gpt-4o"}, "debug": True}),
            encoding="utf-8",
        )
        config_module.save_skip_permissions(True)

        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert raw["skip_permissions"] is True
        assert raw["llm"]["model"] == "gpt-4o"
        assert raw["debug"] is True