"""DocGenService:把 Outline 翻译成完整文档树并落盘。

流程:
1. build_doc_tree_structure 生成章节骨架
2. 逐 section 填 content(guide 在最后用完整 tree 渲染,防 REPO_GUIDE.md 空 sections bug)
3. 落盘到 <source_root>/.code-reader/docs/
"""

from __future__ import annotations

from pathlib import Path

from ..deepwriter.service import DeepWriterService
from ..llm_client import LLMClient, MockLLM
from ..storage.paths import PathManager
from ..types import DocSection, DocTree, Outline, RepoIndex
from .render import render_guide, render_section
from .tree import build_doc_tree_structure


class DocGenService:
    """文档树生成 + 落盘服务。"""

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        repo_name: str,
        language: str = "zh",
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.repo_name = repo_name
        self.language = language
        self.deepwriter = DeepWriterService(llm=llm, source_root=source_root)

    def generate(self, idx: RepoIndex, outline: Outline) -> DocTree:
        """生成完整文档树并落盘,返回 DocTree。"""
        sections = build_doc_tree_structure(outline, self.repo_name, self.language)

        # 先填非 guide 章节内容
        for s in sections:
            if s.kind == "guide":
                continue
            s.content = self._render_section_content(s, idx, outline)

        # guide 在最后渲染:传入完整 tree,链接列表才会包含所有章节
        guide_section = next(s for s in sections if s.kind == "guide")
        full_tree = DocTree(repo_name=self.repo_name, language=self.language, sections=sections)
        guide_section.content = render_guide(full_tree, outline)

        tree = DocTree(repo_name=self.repo_name, language=self.language, sections=sections)
        # 落盘
        self._write_to_disk(tree)
        return tree

    def _render_section_content(self, section: DocSection, idx: RepoIndex, outline: Outline) -> str:
        """分派渲染单章节正文(guide 走特殊路径,在 generate() 末尾渲染)。"""
        if section.kind == "guide":
            # 不会走到这里,generate() 在末尾特判 guide
            return render_guide(
                DocTree(repo_name=self.repo_name, language=self.language, sections=[]),
                outline,
            )
        if section.kind == "overview":
            # Task 12 的 agent 循环会填
            return "(待 agent 填充)"
        if section.kind == "mechanism":
            name = section.title
            m = next((x for x in outline.selected_mechanisms if x.name == name), None)
            if m:
                return self.deepwriter.write_mechanism(idx, m)
            return "(机制未找到)"
        if section.kind == "flow":
            name = section.title
            f = next((x for x in outline.flow_candidates if x.name == name), None)
            if f:
                return self.deepwriter.write_flow(idx, f)
            return "(流程未找到)"
        if section.kind == "module":
            path = section.title
            m = next(
                (x for x in outline.module_candidates if (x.path or "根目录") == path),
                None,
            )
            if m:
                return self.deepwriter.write_module(idx, m)
            return "(模块未找到)"
        if section.kind == "glossary":
            return "(待 agent 填充)"
        if section.kind == "reading_map":
            return self._render_reading_map(outline)
        return ""

    def _render_reading_map(self, outline: Outline) -> str:
        """阅读路线图:按"想改什么 → 读哪"组织。"""
        lines: list[str] = ["想改某类问题,先读这些:", ""]
        for m in outline.selected_mechanisms[:5]:
            lines.append(f"- 想改 **{m.name}** 相关 → 读 02_核心机制/")
        for f in outline.flow_candidates[:3]:
            lines.append(f"- 想改 **{f.name}** 流程 → 读 03_关键流程/")
        return "\n".join(lines)

    def _write_to_disk(self, tree: DocTree) -> None:
        """把每个 section 落盘到 doc_dir/<section.path>。"""
        doc_dir = PathManager.doc_dir(self.source_root)
        for s in tree.sections:
            full = doc_dir / s.path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(render_section(s, s.content), encoding="utf-8")
