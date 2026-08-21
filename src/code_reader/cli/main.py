"""Code Reader Agent CLI 入口。

命令:
- code-reader index <repo_path>  建索引(本地路径)
- code-reader ask "<question>" --repo <path>  问问题
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
from ..indexer.service import IndexerService
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..storage.paths import PathManager
from ..summarizer.service import SummarizerService
from ..types import RepoMap


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
            * 10
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
    repo_map = summarizer.summarize(idx, source_root=source_root)
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


@cli.command("ask")
@click.argument("question")
@click.option("--repo", required=True, help="本地 repo 路径(必须先 index 过)")
def cmd_ask(question: str, repo: str) -> None:
    """问问题,Agent 跨文件追踪调用链回答。"""
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(
            f"错误:路径不存在或不是目录: {source_root}",
            err=True,
        )
        sys.exit(1)

    pm = PathManager()
    repo_map_path = pm.repo_map_path(source_root)
    if not repo_map_path.exists():
        click.echo(f"错误:repo 未索引过,请先 `code-reader index {source_root}`", err=True)
        sys.exit(1)

    repo_map = RepoMap.model_validate_json(repo_map_path.read_text(encoding="utf-8"))

    indexer = IndexerService(pm)
    idx = indexer.update(source_root)
    call_graph = indexer.build_call_graph(idx)

    llm = _make_llm()
    agent = AgentService(
        llm=llm,
        source_root=source_root,
        call_graph=call_graph,
        repo_map=repo_map,
    )
    answer = agent.run(question)
    click.echo(answer.text)
    if answer.citations:
        click.echo("\n引用:")
        for c in answer.citations:
            click.echo(f"  - {c.file}:{c.line_range[0]}-{c.line_range[1]}")


if __name__ == "__main__":
    cli()
