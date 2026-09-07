"""autocompact 通用对话摘要 prompt(改造自 Claude Code 原版,适配 coding agent 任务)。

LLM 被强制走纯文本路径(不带 tools),输出一个 <analysis> 块加一个 <summary> 块。
autocompact 主流程只保留 <summary> 块作为压缩后的对话记忆。
"""

NO_TOOLS_PREAMBLE = """关键约束:只用纯文本回复。不要调用任何工具。

- 你已经拥有所需的所有上下文,都在上面的对话里。
- 你的整个回复必须是纯文本:一个 <analysis> 块跟着一个 <summary> 块。"""

BASE_COMPACT_PROMPT = """你的任务是创建一份到目前为止对话的详细摘要,
让 agent 在压缩后能继续帮用户处理代码任务。

摘要应包含:
1. 用户的目标(在做什么)
2. 已经完成的步骤(改了哪些文件、跑了什么命令)
3. 还没完成的步骤
4. 关键文件清单(路径 + 一句话用途)
5. 关键决策点(为什么这么改)
6. 当前状态(下一步该做什么)
7. 注意事项(用户偏好、踩坑点)
"""

NO_TOOLS_TRAILER = """提醒:不要调用任何工具。只用纯文本回复——
一个 <analysis> 块跟着一个 <summary> 块。"""


DEFAULT_AUTOCOMPACT_PROMPT = (
    NO_TOOLS_PREAMBLE
    + "\n\n"
    + BASE_COMPACT_PROMPT
    + "\n\n对话内容:\n\n{conversation}\n\n"
    + NO_TOOLS_TRAILER
)


def get_autocompact_prompt(conversation_text: str) -> str:
    """返回 autocompact 完整 prompt:config 自定义 > 默认三段拼接。

    用户自定义文本应含 {conversation} 占位符(保存校验在 web 层加入)。
    运行时把 {conversation} 替换为对话文本;用 str.replace 而非 str.format,
    避免用户文本含其他 {xxx} 或字面花括号时抛 KeyError。
    """
    from ..config import load_prompts

    override = load_prompts().autocompact_prompt
    template = DEFAULT_AUTOCOMPACT_PROMPT if override.use_default or not override.value else override.value
    return template.replace("{conversation}", conversation_text)
