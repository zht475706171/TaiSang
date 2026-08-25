# src/code_reader/session_memory/template.py
"""session memory 笔记 10 章节模板(改造自 Claude Code 原文,适配文档生成任务)。"""

DEFAULT_TEMPLATE = """# Session Title
*当前在为哪个 repo 生成文档*

(demo repo)

# Current State
*整体进度:已完成几章 / 总共几章*

(待填)

# Task specification
*用户要的"吃透级别"和语言*

(待填)

# Files and Functions
*已读过的关键文件 + 关键 symbol*

(待填)

# Workflow
*agent 的工作策略(先挖机制 / 先挖流程)*

(待填)

# Errors & Corrections
*调用图断链、LLM 摘要失败等*

(待填)

# Codebase and System Documentation
*repo 的架构理解(从 indexer 来)*

(待填)

# Learnings
*这个 repo 的特殊性、踩坑点*

(待填)

# Key results
*已生成的章节清单(标题 + 路径 + 一句话定位)*

(待填)

# Worklog
*步骤流水(每 3 次工具调用追加一条)*

(待填)
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
