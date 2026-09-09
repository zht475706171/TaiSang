"""集成测试:画像注入 system prompt 的端到端验证。

覆盖:
- 新 session 启动注入画像段
- 空画像不注入段
- 画像段位置(基础 prompt 后,skills/mcp/agents 前)
- update_profile 工具不碰当前 session ctx(cache 不废)
- autocompact 后重注入最新画像
"""

from __future__ import annotations

from pathlib import Path

from taisang.agent_core.context import ContextManager
from taisang.agent_core.prompts import build_system_prompt
from taisang.user_profile.format import format_profile_section
from taisang.user_profile.store import load_profile, save_profile_field


def test_new_session_injects_profile(tmp_path):
    """新 session __init__ 后,system prompt 含画像段。"""
    sp = tmp_path / "settings.json"
    save_profile_field("tech_stack", "Python/Go", source="user", session_id=None, settings_path=sp)

    profile = load_profile(settings_path=sp)
    profile_section = format_profile_section(profile)
    system = build_system_prompt("", "", "", profile_section)

    assert "## 用户画像" in system
    assert "### 技术栈" in system
    assert "Python/Go" in system


def test_new_session_empty_profile_no_section(tmp_path):
    """空画像 → system prompt 无 ## 用户画像 段头(SYSTEM_PROMPT 里有说明文字,但段头不出现)。"""
    sp = tmp_path / "settings.json"  # 不存在
    profile = load_profile(settings_path=sp)
    profile_section = format_profile_section(profile)
    system = build_system_prompt("", "", "", profile_section)

    # PROFILE_SECTION_HEADER 是 "\n\n## 用户画像\n",空画像不注入这个段头
    # SYSTEM_PROMPT 里有"用户画像(认识用户)"说明文字,但不是 ## 段头
    assert "\n## 用户画像\n" not in system


def test_profile_section_is_first_after_base(tmp_path):
    """画像段在最前(基础 prompt 后,skills/mcp/agents 前)。"""
    sp = tmp_path / "settings.json"
    save_profile_field("tech_stack", "Python", source="user", session_id=None, settings_path=sp)

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

    save_profile_field 只碰 settings.json,不碰任何 ctx 对象。
    """
    sp = tmp_path / "settings.json"
    save_profile_field("tech_stack", "Python", source="user", session_id=None, settings_path=sp)

    # ctx 是独立对象,save 不碰它
    ctx = ContextManager(token_budget=100000)
    ctx.append_system(build_system_prompt("", "", "", format_profile_section(load_profile(sp))))
    system_before = ctx.messages()[0]["content"]

    save_profile_field("tech_stack", "Go", source="agent", session_id="s1", settings_path=sp)

    system_after = ctx.messages()[0]["content"]
    assert system_before == system_after  # ctx 没动


def test_autocompact_reinject_path_loads_latest(tmp_path):
    """autocompact 重注入路径:save 后 load 拿到新值,format 出新段。

    这是 _reinject_profile_into_system 的核心逻辑验证(不构造完整 AgentService,
    只验证数据流:save → load → format → 新 system prompt 含新画像)。
    """
    sp = tmp_path / "settings.json"
    save_profile_field("tech_stack", "Python", source="user", session_id=None, settings_path=sp)

    # 模拟 autocompact 前的 system prompt
    profile_before = load_profile(settings_path=sp)
    system_before = build_system_prompt("", "", "", format_profile_section(profile_before))
    assert "Python" in system_before
    assert "Go" not in system_before

    # agent 在 session 中调 update_profile(不碰 ctx)
    save_profile_field("tech_stack", "Go", source="agent", session_id="s", settings_path=sp)

    # autocompact 触发 → _reinject_profile_into_system 重建 system prompt
    profile_after = load_profile(settings_path=sp)
    system_after = build_system_prompt("", "", "", format_profile_section(profile_after))

    assert "Go" in system_after
    assert "Python" not in system_after  # 整栏覆盖,旧的没了