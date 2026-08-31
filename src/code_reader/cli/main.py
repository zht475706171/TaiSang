"""Code Reader Agent CLI 入口。

提供 `chat` 子命令:进入交互式 REPL coding agent。
- 读用户 query → AgentService.run → 实时渲染 thinking/tool/result/answer 事件
- /exit 退出,/reset 清上下文(TODO)

环境变量:
- CODE_READER_MOCK_LLM=1  使用 MockLLM(测试用,返回固定回答)
- CODE_READER_LLM_*  LLM 配置
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ..agent_core.confirm import default_confirmer
from ..agent_core.events import FINAL_ANSWER, LLM_THINKING, TOOL_CALL, TOOL_RESULT
from ..agent_core.service import AgentService
from ..config import load_config
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..session_memory.service import SessionMemoryService
from ..storage.paths import PathManager


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


@click.group()
def cli() -> None:
    """Code Reader Agent - 简化版 coding agent。"""


@cli.command()
@click.option("--repo", default=".", help="工作目录(默认当前目录)")
def chat(repo: str) -> None:
    """进入交互式 coding agent。"""
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(f"错误:{source_root} 不是目录", err=True)
        sys.exit(1)

    llm = _make_llm()
    confirmer = default_confirmer  # 交互式 y/n
    session_mem = SessionMemoryService(
        llm=llm,
        memory_path=PathManager.session_memory_path(source_root, "main"),
    )
    session_mem.ensure_file()

    agent = AgentService(
        llm=llm,
        source_root=source_root,
        confirmer=confirmer,
        session_memory=session_mem,
    )

    click.echo(f"code-reader agent @ {source_root}")
    click.echo("输入 /exit 退出,/reset 清上下文")

    while True:
        try:
            query = click.prompt(">", type=str).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nbye")
            break
        if not query:
            continue
        if query == "/exit":
            break
        if query == "/reset":
            agent.reset()
            click.echo("(上下文已重置,session memory 笔记保留)")
            continue

        def _render(evt) -> None:
            if evt.type == LLM_THINKING:
                click.echo("  [thinking]")
            elif evt.type == TOOL_CALL:
                click.echo(f"  [tool] {evt.payload['name']} {evt.payload['args']}")
            elif evt.type == TOOL_RESULT:
                p = evt.payload
                click.echo(f"  [result] {p['name']} ({p['total_bytes']} bytes)")
            elif evt.type == FINAL_ANSWER:
                click.echo("")
                click.echo(evt.payload["text"])

        answer = agent.run(query, on_event=_render)
        if not answer.complete:
            click.echo(f"(incomplete: {answer.text})")


if __name__ == "__main__":
    cli()
