"""Code Reader Agent CLI 入口。

命令:
- code-reader index <repo_path>  建索引(本地路径)
- code-reader doc <repo_path>  生成可读文档树(骨架,后续 task 填充)
- code-reader --help  帮助

环境变量:
- CODE_READER_MOCK_LLM=1  使用 MockLLM(测试用,返回固定回答)
- CODE_READER_LLM_*  LLM 配置
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ..agent_core.service import AgentService
from ..config import load_config
from ..docgen.tree import build_doc_tree_structure
from ..indexer.service import IndexerService
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..outliner.service import OutlinerService
from ..session_memory.service import SessionMemoryService
from ..storage.paths import PathManager
from ..summarizer.service import SummarizerService


def _normalize_path(path: str) -> Path:
    """规范化路径:展开 ~ + resolve。"""
    return Path(os.path.expanduser(path)).resolve()


def _make_llm():
    """根据环境决定用真 LLM 还是 MockLLM。"""
    if os.environ.get("CODE_READER_MOCK_LLM") == "1":
        return MockLLM(
            [
                LLMResponse(text="(mock) 这个 repo 定义了 main 函数 [a.py:1]", tool_calls=[]),
            ]
            * 50
        )
    cfg = load_config()
    if not cfg.api_key:
        click.echo(
            "错误:未配置 LLM API key。请设置 CODE_READER_LLM_API_KEY 环境变量,"
            "或写 ~/.code-reader/settings.json。测试可用 CODE_READER_MOCK_LLM=1。",
            err=True,
        )
        sys.exit(2)
    return LLMClient(cfg)


def _make_progress():
    """返回 summarizer 进度回调。"""
    return lambda stage, path, status, detail: click.echo(
        "  {} {}: {}{}".format(
            "✓" if status == "ok" else "✗",
            stage,
            path or "(根目录)",
            f" ({detail})" if detail else "",
        )
    )


@click.group()
def cli() -> None:
    """Code Reader Agent - 3 分钟让陌生代码库变成可问答。"""


@cli.command("index")
@click.argument("repo_path")
def cmd_index(repo_path: str) -> None:
    """建索引:扫本地 repo → 解析 AST → 三层摘要 → 入库。

    索引产物落到 <repo_path>/.code-reader/。
    """
    source_root = _normalize_path(repo_path)
    if not source_root.is_dir():
        click.echo(
            f"错误:路径不存在或不是目录: {source_root}。"
            f"v1 不再支持远程 git clone,请先 `git clone` 到本地再 index。",
            err=True,
        )
        sys.exit(1)

    # 先建 LLM(fail fast:无 key 直接退出,不浪费 AST 解析)
    llm = _make_llm()

    pm = PathManager()
    click.echo(f"开始索引: {source_root}")
    indexer = IndexerService(pm)
    idx = indexer.build(source_root)
    click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")
    if idx.index_errors:
        click.echo(f"  失败文件 {len(idx.index_errors)} 个(已跳过)")

    summarizer = SummarizerService(llm=llm)
    click.echo("生成三层摘要...")
    repo_map = summarizer.summarize(idx, source_root=source_root, on_progress=_make_progress())
    pm.repo_map_path(source_root).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")
    n_files = len(repo_map.file_summaries)
    n_modules = len(repo_map.module_summaries)
    click.echo(f"摘要完成: {n_files} 文件, {n_modules} 模块")
    if summarizer.errors:
        click.echo(f"  摘要失败 {len(summarizer.errors)} 个(已跳过)")
    click.echo("✓ 索引完成")
    click.echo(
        f"提示:索引产物已落到 {source_root}/.code-reader/。建议把 .code-reader/ 加到 .gitignore"
    )


@cli.command("doc")
@click.argument("repo_path")
@click.option("--lang", default="auto", help="产物语言:zh/en/auto")
@click.option("--update", is_flag=True, default=False, help="增量更新模式")
@click.option("--force", is_flag=True, default=False, help="强制全量重生成")
def cmd_doc(repo_path: str, lang: str, update: bool, force: bool) -> None:
    """生成可读文档树,让人能读完吃透这个 repo。"""
    source_root = _normalize_path(repo_path)
    if not source_root.is_dir():
        click.echo(f"错误:路径不存在或不是目录: {source_root}", err=True)
        sys.exit(1)

    # 语言检测
    if lang == "auto":
        lang = "zh"  # v0.1 简化:默认中文

    llm = _make_llm()
    pm = PathManager()

    click.echo(f"开始为 {source_root} 生成文档...")

    # 1. indexer(--update 且非 --force 走增量;否则全量)
    indexer = IndexerService(pm)
    if update and not force:
        # 增量:indexer.update 复用已有 fingerprints,只重解析变动文件。
        # v0.1 简化:索引层增量,文档层仍全量重生成。v0.2 再做文档层增量。
        idx = indexer.update(source_root)
        click.echo("增量模式:索引增量更新 + 文档重生成")
    else:
        idx = indexer.build(source_root)
        click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")

    # 2. summarizer
    summarizer = SummarizerService(llm=llm)
    repo_map = summarizer.summarize(idx, source_root=source_root, on_progress=_make_progress())
    pm.repo_map_path(source_root).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")

    # 3. outliner
    outliner = OutlinerService(llm=llm)
    outline = outliner.outline(idx)
    click.echo(
        f"重点挖掘: {len(outline.selected_mechanisms)} 机制, "
        f"{len(outline.flow_candidates)} 流程, {len(outline.module_candidates)} 模块"
    )

    # 4. docgen 准备章节树(只搭骨架占位,真正内容由 agent 填)
    sections = build_doc_tree_structure(outline, repo_name=source_root.name, language=lang)
    all_section_paths = [s.path for s in sections]
    doc_dir = pm.doc_dir(source_root)
    # 预先创建占位文件(force 时重写)
    for s in sections:
        full = doc_dir / s.path
        full.parent.mkdir(parents=True, exist_ok=True)
        if not full.exists() or force:
            full.write_text(f"# {s.title}\n\n(待填)\n", encoding="utf-8")

    # 5. agent 跑主循环(on_event 传 None,CLI 自己 echo 阶段性进度就够了)
    call_graph = indexer.build_call_graph(idx)
    session_mem = SessionMemoryService(
        llm=llm,
        memory_path=pm.session_memory_path(source_root, "main"),
    )
    agent = AgentService(
        llm=llm,
        source_root=source_root,
        call_graph=call_graph,
        repo_map=repo_map,
        idx=idx,
        outline=outline,
        doc_dir=doc_dir,
        all_sections=all_section_paths,
        session_memory=session_mem,
    )
    click.echo("agent 开始生成文档...")
    answer = agent.run(
        f"为 {source_root.name} 这个 repo 生成完整文档树,语言: {lang}",
        on_event=None,
    )
    click.echo(answer.text)
    click.echo(f"✓ 文档生成完成,产物在 {doc_dir}")


if __name__ == "__main__":
    cli()
