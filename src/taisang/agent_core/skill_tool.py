"""Skill 工具:把 SKILL.md 正文注入 ctx 作为 user 消息。

LLM 调用本工具来"打开"一个 skill。本工具不做真正的执行,只负责把
SKILL.md 的正文(做变量替换 + allowed_tools 提示 + 用户参数段)作为
一条 user 消息注入 ContextManager,然后 LLM 继续往下走、按照注入的
SKILL.md 内容去调其它工具。

注入时机:run() 只把正文放进 pending 队列,等主循环把本轮全部 tool_result
append 完后调 flush() 才真正 append_user。OpenAI 协议要求
assistant(tool_calls) 后紧跟 tool 消息,user 注入必须排在 tool_result 之后。

设计要点:
- 权限:v1 全部自动允许,不调 confirmer(skill 本身只是文本注入,无副作用)。
- allowed_tools:不硬拦,只在注入正文前追加一条提示段,告诉 LLM 执行本
  skill 期间只用这些工具;真正硬拦留给后续版本(基于 ToolRegistry 调度
  时检查)。
- ${TAISANG_SKILL_DIR}:替换成 skill.dir_path 的绝对路径,反斜杠转正
  斜杠(Windows 路径友好)。让 SKILL.md 内可以引用自己目录下的脚本/资源。
- args(可选):用户调用 skill 时传入的参数文本,追加为 `## 用户传入参数`
  段,LLM 能看到调用方意图。
"""

from __future__ import annotations

from ..skills.types import Skill
from .tools import _BaseTool


class SkillTool(_BaseTool):
    """调用 skill,把 SKILL.md 正文注入 ctx 作为 user 消息,tool_result 触发 LLM 继续。

    权限:v1 全部自动允许,不调 confirmer。
    allowed_tools:注入时在正文前追加提示段,不硬拦。
    ${TAISANG_SKILL_DIR}:替换成 skill.dir_path 绝对路径(反斜杠转正斜杠)。
    """

    name = "skill"

    def __init__(self, skills: list[Skill], ctx) -> None:
        """初始化。

        skills:可用 skill 列表(loader 产出)。内部按 name 建字典便于按名查找。
        ctx:ContextManager 实例,flush() 时 append_user 注入 SKILL.md 正文。
            None 时(测试场景)注入内容滞留 pending 队列,不报错。
        """
        self.skills = {s.name: s for s in skills}
        self.ctx = ctx  # ContextManager,flush() 时 append_user 注入 SKILL.md
        self.pending: list[str] = []  # 待注入正文,等 tool_result 写完再 flush

    def schema(self) -> dict:
        """返回 OpenAI function schema。"""
        return {
            "name": self.name,
            "description": (
                "调用一个 skill 执行特定任务。可用 skill 清单见 system prompt。"
                "用 skill name 调用,可选 args 传参数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "skill 名称"},
                    "args": {"type": "string", "description": "可选参数文本"},
                },
                "required": ["skill"],
            },
        }

    def run(self, args: dict) -> dict:
        """执行 skill 调用:查表 -> 校验 disabled -> 正文入队 -> 返回 tool_result。

        正文不立即 append_user,先进 pending 队列,由 AgentService 主循环在本轮
        全部 tool_result 写完后调 flush() 注入。OpenAI 协议要求
        assistant(tool_calls) 后紧跟 tool 消息,user 注入必须排在 tool_result
        之后,严格 provider 才不会 400。

        args:
          - skill: skill 名称(必填)
          - args: 可选参数文本(追加为 `## 用户传入参数` 段)

        返回:
          - {"error": "skill not found"} — 名称不在已注册 skill 表
          - {"error": "skill disabled"} — skill 被 disabled 标记
          - {"ok": True, "injected": True, "skill": name} — 正文已入队
        """
        name = args.get("skill", "")
        skill = self.skills.get(name)
        if skill is None:
            return {"error": "skill not found"}
        if skill.disabled:
            return {"error": "skill disabled"}
        content = self._inject(skill, args.get("args", ""))
        self.pending.append(content)
        return {"ok": True, "injected": True, "skill": name}

    def flush(self) -> None:
        """把 pending 队列里的 SKILL.md 正文依次 append_user 注入 ctx 并清空。

        AgentService 在本轮所有 tool_result append 完之后调用,保证消息序
        assistant(tool_calls) → tool → user(SKILL.md) 符合 OpenAI 协议。
        """
        if self.ctx is None:
            self.pending.clear()
            return
        for content in self.pending:
            self.ctx.append_user(content)
        self.pending.clear()

    def _inject(self, skill: Skill, args: str) -> str:
        """构造注入到 ctx 的 SKILL.md 正文。

        依次拼装:
        1. allowed_tools 提示段(若 skill.allowed_tools 非 None):
           `> 执行本 skill 期间,只允许使用以下工具: X, Y`
        2. 正文标题 `# Skill: <name>` + 空行
        3. SKILL.md 正文(已做 ${TAISANG_SKILL_DIR} 替换)
        4. 用户传入参数段(若 args 非空):`## 用户传入参数\\n<args>`

        ${TAISANG_SKILL_DIR} 替换为 skill.dir_path 绝对路径,反斜杠转正斜杠。
        """
        content = skill.content
        # ${TAISANG_SKILL_DIR} 替换
        skill_dir = str(skill.dir_path.resolve()).replace("\\", "/")
        content = content.replace("${TAISANG_SKILL_DIR}", skill_dir)
        # allowed_tools 提示段
        header = ""
        if skill.allowed_tools is not None:
            tools_list = ", ".join(skill.allowed_tools)
            header = f"> 执行本 skill 期间,只允许使用以下工具: {tools_list}\n\n"
        # args 参数段
        args_block = ""
        if args:
            args_block = f"\n\n## 用户传入参数\n{args}"
        return f"{header}# Skill: {skill.name}\n\n{content}{args_block}"