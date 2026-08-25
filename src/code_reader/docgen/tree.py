"""文档树结构生成:根据 outline 自适应切片出章节骨架。

只产骨架(path/title/kind),content 留空,由 DocGenService 填。
"""

from __future__ import annotations

from ..types import DocSection, Outline


def build_doc_tree_structure(outline: Outline, repo_name: str, language: str) -> list[DocSection]:
    """根据 outline 自适应生成章节树结构(content 全空)。

    章节顺序:
    - REPO_GUIDE.md(总入口)
    - 00_项目是什么.md / 01_架构总览.md(overview,固定两章)
    - 02_核心机制/<NN>_<slug>.md(每个 selected_mechanism 一篇)
    - 03_关键流程/<NN>_<slug>.md(每个 flow_candidate 一篇)
    - 04_核心模块/<NN>_<slug>.md(每个 module_candidate 一篇,根目录 → "根目录")
    - 05_概念词典.md / 06_阅读路线图.md
    """
    sections: list[DocSection] = [
        DocSection(path="REPO_GUIDE.md", title=f"{repo_name} 阅读指南", kind="guide"),
        DocSection(path="00_项目是什么.md", title="项目是什么", kind="overview"),
        DocSection(path="01_架构总览.md", title="架构总览", kind="overview"),
    ]
    # 02_核心机制/:每个机制一个文件
    for i, m in enumerate(outline.selected_mechanisms, start=1):
        slug = _slugify(m.name)
        sections.append(
            DocSection(
                path=f"02_核心机制/{i:02d}_{slug}.md",
                title=m.name,
                kind="mechanism",
            )
        )
    # 03_关键流程/:每个流程一个文件
    for i, f in enumerate(outline.flow_candidates, start=1):
        slug = _slugify(f.name)
        sections.append(
            DocSection(
                path=f"03_关键流程/{i:02d}_{slug}.md",
                title=f.name,
                kind="flow",
            )
        )
    # 04_核心模块/:每个模块一个文件(根目录 → "根目录",中文标题)
    for i, m in enumerate(outline.module_candidates, start=1):
        title = m.path or "根目录"
        slug = _slugify(title)
        sections.append(
            DocSection(
                path=f"04_核心模块/{i:02d}_{slug}.md",
                title=title,
                kind="module",
            )
        )
    sections.append(DocSection(path="05_概念词典.md", title="概念词典", kind="glossary"))
    sections.append(DocSection(path="06_阅读路线图.md", title="阅读路线图", kind="reading_map"))
    return sections


def _slugify(name: str) -> str:
    """转文件名安全的 slug(保留中文,去掉空格和斜杠)。"""
    return name.replace(" ", "_").replace("/", "_")[:50]
