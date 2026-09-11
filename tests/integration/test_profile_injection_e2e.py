"""集成测试:画像注入 system prompt 的端到端验证。

覆盖:
- 新 session 启动注入画像段
- 空 content 不注入段
- 画像段位置(基础 prompt 后,skills/mcp/agents 前)
- update_profile 工具不碰当前 session ctx(cache 不废)
- autocompact 后重注入最新画像
"""

from __future__ import annotations

from taisang.agent_core.context import ContextManager
from taisang.agent_core.prompts import build_system_prompt
from taisang.user_profile.format import format_profile_section
from taisang.user_profile.store import load_profile, save_profile_content


def test_new_session_injects_profile(tmp_path):
    """新 session __init__ 后,system prompt 含画像段。"""
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython/Go", source="user", session_id=None, settings_path=sp)

    profile = load_profile(settings_path=sp)
    profile_section = format_profile_section(profile)
    system = build_system_prompt("", "", "", profile_section)

    assert "## 用户画像" in system
    assert "### 技术栈" in system
    assert "Python/Go" in system


def test_new_session_empty_content_no_section(tmp_path):
    """空 content → system prompt 无 ## 用户画像 段头。"""
    sp = tmp_path / "settings.json"  # 不存在
    profile = load_profile(settings_path=sp)
    profile_section = format_profile_section(profile)
    system = build_system_prompt("", "", "", profile_section)

    # PROFILE_SECTION_HEADER 是 "\n\n## 用户画像\n",空 content 不注入
    assert "\n## 用户画像\n" not in system


def test_profile_section_is_first_after_base(tmp_path):
    """画像段在最前(基础 prompt 后,skills/mcp/agents 前)。"""
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython", source="user", session_id=None, settings_path=sp)

    profile = load_profile(settings_path=sp)
    profile_section = format_profile_section(profile)
    system = build_system_prompt("SKILLS_CONTENT", "MCP_CONTENT", "AGENTS_CONTENT", profile_section)

    idx_profile = system.index("## 用户画像")
    idx_skills = system.index("## 可用 Skills")
    idx_mcp = system.index("## MCP 服务器")
    idx_agents = system.index("## 可用 Agents")

    assert idx_profile < idx_skills < idx_mcp < idx_agents


def test_update_profile_tool_does_not_change_current_session_system(tmp_path):
    """agent 调 update_profile 后,当前 session 的 ctx system prompt 不变(cache 不废)。

    save_profile_content 只碰 settings.json,不碰任何 ctx 对象。
    """
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython", source="user", session_id=None, settings_path=sp)

    ctx = ContextManager(token_budget=100000)
    ctx.append_system(build_system_prompt("", "", "", format_profile_section(load_profile(sp))))
    system_before = ctx.messages()[0]["content"]

    save_profile_content("### 技术栈\nGo", source="agent", session_id="s1", settings_path=sp)

    system_after = ctx.messages()[0]["content"]
    assert system_before == system_after  # ctx 没动


def test_autocompact_reinject_path_loads_latest(tmp_path):
    """autocompact 重注入路径:save 后 load 拿到新值,format 出新段。"""
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython", source="user", session_id=None, settings_path=sp)

    profile_before = load_profile(settings_path=sp)
    system_before = build_system_prompt("", "", "", format_profile_section(profile_before))
    assert "Python" in system_before
    assert "Go" not in system_before

    # agent 在 session 中调 update_profile(不碰 ctx)
    save_profile_content("### 技术栈\nGo", source="agent", session_id="s", settings_path=sp)

    # autocompact 触发 → _refresh_system_prompt 重建 system prompt(压缩前刷新)
    profile_after = load_profile(settings_path=sp)
    system_after = build_system_prompt("", "", "", format_profile_section(profile_after))

    assert "Go" in system_after
    assert "Python" not in system_after  # 整篇覆盖,旧的没了
