# src/code_reader/session_memory/template.py
"""session memory 笔记 10 章节模板(改造自 Claude Code 原文,适配 coding agent 任务)。"""

DEFAULT_TEMPLATE = """# Session Title
*当前在帮用户做什么*

# Current Goal
*用户的目标*

# Completed Steps
*已经完成的步骤(改了哪些文件 / 跑了什么命令)*

# Pending Steps
*还没做的事*

# Files Touched
*改过的关键文件 + 一句话用途*

# Key Decisions
*关键决策点(为什么这么改)*

# Errors & Corrections
*踩过的坑、用户纠正过的事*

# User Preferences
*用户偏好(代码风格、命名习惯等)*

# Learnings
*这个 repo 的特殊性*

# Worklog
*步骤流水(每 3 次工具调用追加一条)*
"""

DEFAULT_UPDATE_PROMPT = """你是一个会话笔记维护助手。下面是当前笔记内容,请根据最新的对话更新它。

【当前笔记】:
{current_notes}

【最新对话片段】:
{recent_conversation}

更新规则:
1. 只改每个章节描述行下面的实际内容,描述行(以 * 开头)必须保留
2. 章节顺序固定,不要新增或删除章节
3. Worklog 章节追加新条目,不要删除旧条目
4. 用 Edit 工具修改 {memory_path},一次只改一个章节
5. 不要调用任何其他工具

开始更新。"""


def get_template() -> str:
    """返回默认 10 章节模板文本。"""
    return DEFAULT_TEMPLATE


def get_update_prompt(current_notes: str, recent_conversation: str, memory_path: str) -> str:
    """根据当前笔记 + 最新对话片段 + 笔记路径,组装更新 prompt。"""
    return DEFAULT_UPDATE_PROMPT.format(
        current_notes=current_notes,
        recent_conversation=recent_conversation,
        memory_path=str(memory_path),
    )
