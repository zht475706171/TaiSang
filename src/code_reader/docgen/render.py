"""markdown 渲染:REPO_GUIDE.md + 单章节。

render_guide 渲染总入口,列出所有章节链接;
render_section 给单个章节套标题 + 正文。
"""

from __future__ import annotations

from ..types import DocSection, DocTree, Outline


def render_guide(tree: DocTree, outline: Outline) -> str:
    """渲染 REPO_GUIDE.md:标题 + 阅读顺序说明 + 全章节链接列表。

    要求传入的 tree.sections 是已建好的完整骨架,这样链接列表才不会空。
    """
    lines: list[str] = [
        f"# {tree.repo_name} 阅读指南",
        "",
        "## 这份文档怎么读",
        "",
        "按以下顺序阅读,30 分钟内能吃透这个项目:",
        "",
    ]
    for s in tree.sections:
        if s.path == "REPO_GUIDE.md":
            continue
        lines.append(f"- [{s.title}]({s.path})")
    lines += ["", "## 项目一句话", "", "(待 00_项目是什么.md 填充)"]
    return "\n".join(lines)


def render_section(section: DocSection, content: str) -> str:
    """渲染单个章节文件内容:加一级标题 + 正文。"""
    return f"# {section.title}\n\n{content}\n"
