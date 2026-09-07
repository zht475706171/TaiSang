"""Agent system prompt。

Task 4 重写:从"为 repo 生成 markdown 文档树"改为"通用 coding agent"。
跟用户对话,读写、修改、调试代码。
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是一个 coding agent,跟用户对话,帮助用户读写、修改、调试代码。

工作模式:
- 用户说一个目标,你调工具查 / 改 / 跑代码
- 每次工具调用后,告诉用户你做了什么、结果如何
- 信息够了或任务完成,给最终答复

工具:
- Read(path):读文件
- Edit(file_path, old_string, new_string):改文件(用户会确认)
- Write(file_path, content):创建/覆盖文件(用户会确认)
- Grep(pattern, scope):正则搜
- Glob(pattern):文件名匹配
- Bash(command):跑 shell 命令(白名单内,限定 cwd)

约束:
- Edit/Write 会触发用户确认,被拒绝就换方案,不要硬来
- Bash 只能跑白名单命令(git/python/pytest/ls/cat 等),危险命令会被拒
- 改代码前先 Read 确认上下文,不要瞎改
- 用 [file:line] 引用代码位置

语言:跟用户同语言(中文或英文)。
"""

SKILLS_SECTION_HEADER = """

## 可用 Skills
"""

MCP_SECTION_HEADER = """

## MCP 服务器
"""


def get_system_prompt() -> str:
    """返回当前生效的主 system prompt:config 自定义 > 代码常量 SYSTEM_PROMPT。"""
    from ..config import load_prompts

    override = load_prompts().system_prompt
    return SYSTEM_PROMPT if override.use_default or not override.value else override.value


def build_system_prompt(skills_section: str = "", mcp_section: str = "") -> str:
    """组装完整 system prompt:基础 prompt(读 config)+ (可选)skills 清单段 + (可选)MCP 能力段。"""
    prompt = get_system_prompt()
    if skills_section:
        prompt += SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
    if mcp_section:
        prompt += MCP_SECTION_HEADER + "\n" + mcp_section + "\n"
    return prompt


def format_mcp_section(manager) -> str:
    """格式化 MCP 能力段,注入 system prompt。

    仅列出已 connected 的 server 的 tools/resources/prompts。
    无 connected server 时返回空串(不注入段)。
    """
    if not manager:
        return ""
    infos = manager.list_server_info()
    connected = [i for i in infos if i.status == "connected"]
    if not connected:
        return ""

    lines: list[str] = []
    all_tools = manager.get_all_mcp_tools()
    if all_tools:
        lines.append("### 可用 MCP 工具")
        for t in all_tools:
            tool = t["tool_info"]
            lines.append(f"- {t['name']}: {tool.description}")
        lines.append("")

    all_resources = manager.get_all_mcp_resources()
    if all_resources:
        lines.append("### 可用 MCP 资源")
        for r in all_resources:
            res = r["resource"]
            lines.append(f"- {r['server']}: {res.uri} - {res.name}")
        lines.append("")

    all_prompts = manager.get_all_mcp_prompts()
    if all_prompts:
        lines.append("### 可用 MCP 提示")
        for p in all_prompts:
            prompt = p["prompt"]
            lines.append(f"- {p['server']}: {prompt.name} - {prompt.description}")
        lines.append("")

    lines.append("调 MCP 工具: 直接用 mcp__<server>__<tool> 工具名")
    lines.append("读 MCP 资源: 调 mcp_resource(server, uri)")
    lines.append("用 MCP 提示: 调 mcp_prompt(server, name)")
    return "\n".join(lines)
