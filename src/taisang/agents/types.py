from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentDefinition:
    """单个 agent 的定义（从 AGENT.md 加载）。

    字段对应 frontmatter + 正文：
    - agent_type: frontmatter name，跟目录名一致
    - when_to_use: frontmatter description，注入清单用
    - tools: 白名单（None = 全工具）
    - disallowed_tools: 黑名单
    - max_turns: 覆盖默认 max_steps=50（None = 用默认）
    - background: True = 默认 async（verification 用）
    - model: v1 只识别 "inherit"，其他值静默忽略
    - source: "project" / "user" / "system"
    - base_dir: AGENT.md 所在目录
    - system_prompt: AGENT.md 正文（frontmatter 以后的文本）
    - disabled: 从 agents_state.json 读入
    """
    agent_type: str
    when_to_use: str
    tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int | None = None
    background: bool = False
    model: str | None = None
    source: str = "user"
    base_dir: Path = field(default_factory=lambda: Path("."))
    system_prompt: str = ""
    disabled: bool = False