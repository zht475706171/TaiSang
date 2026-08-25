"""docgen 文档树落地测试。

覆盖:
- build_doc_tree_structure:自适应深度(机制/流程/模块各按数量切片)
- render_guide:渲染 REPO_GUIDE.md,目录列表含所有 sections 链接
- DocGenService.generate:落盘文件齐全 + REPO_GUIDE.md 含章节链接 + 04_核心模块/01_根目录.md 成立
"""

from code_reader.docgen.render import render_guide
from code_reader.docgen.tree import build_doc_tree_structure
from code_reader.types import (
    DocTree,
    EntryPoint,
    FlowCandidate,
    MechanismCandidate,
    ModuleCandidate,
    Outline,
)


def _make_outline(
    *,
    n_mechanisms: int = 3,
    n_flows: int = 0,
    n_modules: int = 0,
) -> Outline:
    """构造一个测试用 Outline。"""
    return Outline(
        entry_points=[EntryPoint(symbol_id="main.py::main", kind="main")],
        mechanism_candidates=[],
        flow_candidates=[
            FlowCandidate(
                name=f"flow{i}",
                entry_symbol_id=f"f{i}.py::entry",
                chain=[f"f{i}.py::entry"],
                hop_count=1,
                rendered=f"flow{i} 叙事",
            )
            for i in range(n_flows)
        ],
        module_candidates=[
            ModuleCandidate(
                path="" if i == 0 else f"mod{i}",
                file_count=1,
                symbol_count=1,
                in_degree=0,
            )
            for i in range(n_modules)
        ],
        selected_mechanisms=[
            MechanismCandidate(
                symbol_id=f"f{i}.py::m{i}",
                name=f"m{i}",
                file=f"f{i}.py",
                in_degree=3,
                cross_module_refs=2,
                out_degree=1,
                score=10,
            )
            for i in range(n_mechanisms)
        ],
    )


def test_build_doc_tree_small_repo():
    """小 repo(<5 机制)只生成最少章节。"""
    outline = _make_outline(n_mechanisms=3)
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    paths = [s.path for s in sections]
    assert "REPO_GUIDE.md" in paths
    assert "00_项目是什么.md" in paths
    assert "01_架构总览.md" in paths
    # 3 个机制 → 3 个文件
    mechanism_paths = [p for p in paths if p.startswith("02_核心机制/")]
    assert len(mechanism_paths) == 3
    assert "05_概念词典.md" in paths
    assert "06_阅读路线图.md" in paths


def test_build_doc_tree_structure_kinds():
    """断言生成的 sections 里每种 kind 都有(guide/overview/mechanism/glossary/reading_map)。"""
    outline = _make_outline(n_mechanisms=2, n_flows=1, n_modules=1)
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    kinds = {s.kind for s in sections}
    assert "guide" in kinds
    assert "overview" in kinds
    assert "mechanism" in kinds
    assert "flow" in kinds
    assert "module" in kinds
    assert "glossary" in kinds
    assert "reading_map" in kinds


def test_build_doc_tree_module_root_title():
    """模块 path="" 时 title 为 '根目录',slug 也用 '根目录'(非 'root')。

    这是任务说明里明确要求的中文标题路径,断言 04_核心模块/01_根目录.md 成立。
    """
    outline = _make_outline(n_mechanisms=0, n_modules=1)
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    module_paths = [s.path for s in sections if s.kind == "module"]
    assert module_paths == ["04_核心模块/01_根目录.md"]
    assert sections[-2].title == "根目录" or any(s.title == "根目录" for s in sections)


def test_render_guide_links_to_all_sections():
    """render_guide 渲染含所有 sections 的链接(防 REPO_GUIDE.md 空 sections bug)。"""
    outline = _make_outline(n_mechanisms=2, n_flows=1, n_modules=1)
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    tree = DocTree(repo_name="demo", language="zh", sections=sections)
    rendered = render_guide(tree, outline)
    # 每个非 REPO_GUIDE.md 的 section 都应有一个 markdown 链接
    for s in sections:
        if s.path == "REPO_GUIDE.md":
            continue
        assert f"]({s.path})" in rendered, f"missing link to {s.path}"
    # 具体抽查
    assert "](00_项目是什么.md)" in rendered
    assert "](02_核心机制/01_m0.md)" in rendered
    assert "](04_核心模块/01_根目录.md)" in rendered


def test_docgen_service_writes_files(tmp_path, monkeypatch):
    """DocGenService.generate 落盘 + REPO_GUIDE.md 含链接 + 04_核心模块/01_根目录.md 成立。"""
    from code_reader.docgen.service import DocGenService
    from code_reader.llm_client import LLMResponse, MockLLM
    from code_reader.storage.paths import PathManager
    from code_reader.types import RepoIndex, Symbol, SymbolKind

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    # 50 条响应,防止 mechanism/module 各消耗一条后越界
    mock = MockLLM([LLMResponse(text=f"讲解内容 {i} [a.py:1-2]", tool_calls=[]) for i in range(50)])
    service = DocGenService(llm=mock, source_root=repo, repo_name="demo", language="zh")
    idx = RepoIndex(
        source_root=str(repo),
        commit_hash="x",
        symbols=[
            Symbol(
                id="a.py::foo",
                kind=SymbolKind.FUNCTION,
                name="foo",
                file="a.py",
                line_range=(1, 2),
                calls=[],
                imports=[],
            )
        ],
        files=["a.py"],
        index_errors=[],
    )
    outline = Outline(
        entry_points=[EntryPoint(symbol_id="a.py::foo", kind="main")],
        mechanism_candidates=[],
        flow_candidates=[],
        module_candidates=[ModuleCandidate(path="", file_count=1, symbol_count=1, in_degree=0)],
        selected_mechanisms=[
            MechanismCandidate(
                symbol_id="a.py::foo",
                name="foo",
                file="a.py",
                in_degree=1,
                cross_module_refs=0,
                out_degree=0,
                score=1,
            )
        ],
    )
    tree = service.generate(idx, outline)
    doc_dir = PathManager.doc_dir(repo)

    # 基础文件齐全
    assert (doc_dir / "REPO_GUIDE.md").exists()
    assert (doc_dir / "00_项目是什么.md").exists()
    assert (doc_dir / "02_核心机制" / "01_foo.md").exists()
    # 任务说明明确要求:04_核心模块/01_根目录.md 必须成立
    assert (doc_dir / "04_核心模块" / "01_根目录.md").exists()
    # 返回的 tree 也带 sections
    assert tree.repo_name == "demo"
    assert len(tree.sections) >= 5

    # REPO_GUIDE.md 必须含所有章节链接(防 plan 第 1432 行空 sections bug)
    guide_text = (doc_dir / "REPO_GUIDE.md").read_text(encoding="utf-8")
    assert "](00_项目是什么.md)" in guide_text
    assert "](02_核心机制/01_foo.md)" in guide_text
    assert "](04_核心模块/01_根目录.md)" in guide_text
    assert "](05_概念词典.md)" in guide_text

    # 机制章节正文应该是 LLM 返回的内容,不是占位符
    mech_text = (doc_dir / "02_核心机制" / "01_foo.md").read_text(encoding="utf-8")
    assert "讲解内容" in mech_text
