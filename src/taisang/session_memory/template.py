# src/taisang/session_memory/template.py
"""session memory 笔记 10 章节模板 + 更新 prompt(对齐 Claude Code 中文版)。

模板和 prompt 内容均翻译自 Claude Code `src/services/SessionMemory/prompts.ts`,
10 个 section 名字保持 Claude Code 原版(中文翻译)。
"""

DEFAULT_TEMPLATE = """# Session Title
_简短、信息密集的 5-10 词会话描述性标题,无填充_

# Current State
_当前正在做什么?未完成的待办任务。接下来的直接步骤。_

# Task specification
_用户要求构建什么?任何设计决策或其他解释性上下文_

# Files and Functions
_重要文件有哪些?简述其内容和相关性_

# Workflow
_通常按什么顺序运行哪些 bash 命令?输出不明显时如何解读?_

# Errors & Corrections
_遇到的错误及修复方法。用户纠正了什么?哪些方法失败了不应再试?_

# Codebase and System Documentation
_重要的系统组件有哪些?它们如何工作/配合?_

# Learnings
_什么有效?什么无效?要避免什么?不要重复其他章节的条目_

# Key results
_如果用户要求了特定输出(如问题答案、表格或其他文档),在此重复确切结果_

# Worklog
_逐步记录尝试了什么、完成了什么?每步极简摘要_
"""

DEFAULT_UPDATE_PROMPT = """重要:本消息及以下指令并非真实用户对话的一部分。笔记内容中请勿引用"记笔记"、"会话笔记提取"或这些更新指令。

基于上方的用户对话(排除本记笔记指令消息、system prompt、claude.md 条目及任何过往会话摘要),更新会话笔记文件。

文件 {memory_path} 已为你读取。以下是其当前内容:
<current_notes_content>
{current_notes}
</current_notes_content>

你的唯一任务是使用 Edit 工具更新笔记文件,然后停止。你可以进行多次编辑(按需更新每个章节)— 将所有 Edit 工具调用在单条消息中并行发起。不要调用任何其他工具。

编辑的关键规则:
- 文件必须保持其确切结构,所有章节、标题和斜体描述完整无损
-- 永不修改、删除或新增章节标题(以 # 开头的行,如 # Task specification)
-- 永不修改或删除斜体 _章节描述_ 行(紧跟标题后的斜体行,以下划线开头和结尾)
-- 斜体 _章节描述_ 是模板指令,必须原样保留 — 它们指引每个章节应包含什么内容
-- 仅更新每个现有章节中斜体 _章节描述_ 之后的实际内容
-- 不要在现有结构之外新增任何章节、摘要或信息
- 笔记中任何位置都不要引用本记笔记过程或指令
- 如果某个章节没有实质性新洞察可加,可以跳过更新。不要加"暂无信息"之类的填充内容,合适时留空/不编辑即可
- 为每个章节写详细、信息密集的内容 — 包含具体细节如文件路径、函数名、错误消息、确切命令、技术细节等
- 对于 "Key results",包含用户请求的完整确切输出(如完整表格、完整答案等)
- 不要包含已在上下文的 CLAUDE.md 文件中的信息
- 每个章节保持在 ~2000 token/词以内 — 若接近此限制,通过淘汰次要细节、保留最关键信息来压缩
- 聚焦可操作、具体的信息,能帮助他人理解或重现对话中讨论的工作
- 重要:始终更新 "Current State" 以反映最新工作 — 这对 compaction 后的连续性至关重要

使用 Edit 工具,file_path: {memory_path}

结构保留提醒:
每个章节有两部分必须原样保留:
1. 章节标题(以 # 开头的行)
2. 斜体描述行(标题紧跟的 _斜体文本_ — 这是模板指令)

你只更新这两行之后的实际内容。以下划线开头和结尾的斜体描述行是模板结构的一部分,不是待编辑或删除的内容。

记住:并行使用 Edit 工具然后停止。编辑后不要继续。仅包含真实用户对话中的洞察,
绝不包含本记笔记指令中的内容。不要删除或修改章节标题或斜体 _章节描述_。"""


def get_template() -> str:
    """返回默认 10 章节模板文本。"""
    return DEFAULT_TEMPLATE


def get_update_prompt(current_notes: str, memory_path: str) -> str:
    """根据当前笔记 + 笔记路径,组装更新 prompt。

    注意:recent_conversation 不再拼进 prompt 文本,而是作为独立的 user message
    放在 update 指令之前(对齐 Claude Code 的 [...forkContextMessages, ...promptMessages] 结构)。
    本函数只负责 update 指令本身的模板填充。
    """
    return DEFAULT_UPDATE_PROMPT.format(
        current_notes=current_notes,
        memory_path=str(memory_path),
    )
