"""摘要 prompt 模板。"""

from __future__ import annotations

from ..types import Symbol

FILE_SUMMARY_SYSTEM = """你是代码理解专家。给定一个 Python 文件,用不超过 100 字概括它的作用。
要求:
- 客观、具体,不空话
- 提到关键函数/类的名字和职责
- 不复述源码,要总结
- 中文回答"""

MODULE_SUMMARY_SYSTEM = """你是代码理解专家。给定一个目录下所有文件的摘要,用不超过 300 字概括这个模块的作用。
要求:
- 聚合同目录文件的职责,提炼模块边界
- 指出模块的入口/对外接口(如果有)
- 中文回答"""  # noqa: E501

GLOBAL_SUMMARY_SYSTEM = """你是代码理解专家。给定一个 repo 所有模块的摘要,用不超过 1000 字概括全局架构。
要求:
- 指出入口点(如 main 函数、CLI 入口、Web 路由)
- 指出核心模块及其依赖关系
- 中文回答"""  # noqa: E501


def build_file_summary_prompt(rel_path: str, source: str, symbols: list[Symbol]) -> str:
    sym_list = "\n".join(
        f"- {s.name} ({s.kind.value}, 行 {s.line_range[0]}-{s.line_range[1]})" for s in symbols
    )
    return f"""文件路径: {rel_path}

源码:
```
{source}
```

该文件定义的符号:
{sym_list or '(无符号)'}

请概括这个文件的作用。"""


def build_module_summary_prompt(module_path: str, file_summaries: list[tuple[str, str]]) -> str:
    files_block = "\n".join(f"- {fp}: {summary}" for fp, summary in file_summaries)
    return f"""模块路径: {module_path or '(根目录)'}

该模块下文件的摘要:
{files_block}

请概括这个模块的作用。"""


def build_global_summary_prompt(
    module_summaries: list[tuple[str, str]],
    entry_candidates: list[str],
) -> str:
    modules_block = "\n".join(f"- {mp}: {summary}" for mp, summary in module_summaries)
    entries_block = "\n".join(f"- {e}" for e in entry_candidates) or "(未识别)"
    return f"""以下是 repo 各模块的摘要:

{modules_block}

候选入口点(名为 main / __main__ / run / app 的符号):
{entries_block}

请概括这个 repo 的全局架构。"""
