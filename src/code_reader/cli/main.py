"""Code Reader Agent CLI 入口。

命令:
- code-reader index <repo_url>  建索引
- code-reader ask "<question>" --repo <url>  问问题
- code-reader --help  帮助

环境变量:
- CODE_READER_MOCK_LLM=1  使用 MockLLM(测试用,返回固定回答)
- CODE_READER_LLM_*  LLM 配置
"""

from __future__ import annotations

import os
import sys

import click

from ..agent_core.service import AgentService
from ..config import load_config
from ..indexer.service import IndexerService
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..storage.paths import PathManager
from ..summarizer.service import SummarizerService
from ..types import RepoMap


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
@click.argument("repo_url")
def cmd_index(repo_url: str) -> None:
    """建索引:clone repo → 解析 AST → 三层摘要 → 入库。"""
    pm = PathManager()
    click.echo(f"开始索引: {repo_url}")
    indexer = IndexerService(pm)
    idx = indexer.build(repo_url)
    click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")
    if idx.index_errors:
        click.echo(f"  失败文件 {len(idx.index_errors)} 个(已跳过)")

    # 跑摘要(需要 source_root,从 fetcher cache 取)
    # 简化:从 cache 找 clone 后的目录
    repo_hash = pm._repo_hash(repo_url)
    source_root = pm.cache_dir / repo_hash
    if not source_root.exists():
        click.echo("错误:clone 目录丢失", err=True)
        sys.exit(1)

    llm = _make_llm()
    summarizer = SummarizerService(llm=llm)
    click.echo("生成三层摘要...")
    repo_map = summarizer.summarize(idx, source_root=source_root)
    # 落盘 repo_map
    pm.repo_map_path(repo_url).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")
    n_files = len(repo_map.file_summaries)
    n_modules = len(repo_map.module_summaries)
    click.echo(f"摘要完成: {n_files} 文件, {n_modules} 模块")
    if summarizer.errors:
        click.echo(f"  摘要失败 {len(summarizer.errors)} 个(已跳过)")
    click.echo("✓ 索引完成")


@cli.command("ask")
@click.argument("question")
@click.option("--repo", required=True, help="repo URL(必须先 index 过)")
def cmd_ask(question: str, repo: str) -> None:
    """问问题,Agent 跨文件追踪调用链回答。"""
    pm = PathManager()
    repo_map_path = pm.repo_map_path(repo)
    if not repo_map_path.exists():
        click.echo(f"错误:repo 未索引过,请先 `code-reader index {repo}`", err=True)
        sys.exit(1)

    # 加载 repo_map 和索引
    repo_map = RepoMap.model_validate_json(repo_map_path.read_text(encoding="utf-8"))

    indexer = IndexerService(pm)
    # 走 update(会复用已有索引)
    idx = indexer.update(repo)
    call_graph = indexer.build_call_graph(idx)

    # 找 source_root
    repo_hash = pm._repo_hash(repo)
    source_root = pm.cache_dir / repo_hash

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
