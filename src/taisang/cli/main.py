"""TaiSang CLI 入口。

提供 `chat` 子命令:进入交互式 REPL coding agent。
- 读用户 query → AgentService.run → 实时渲染 thinking/tool/result/answer 事件
- /exit 退出,/reset 清上下文,/debug 切换调试输出(打印发给 LLM 的 messages + 响应 + 工具结果)

提供 `web` 子命令:起本地 FastAPI 服务 + 自动开浏览器,豆包风格 Web UI。
- 多会话列表 / Markdown 渲染 / 代码高亮 / 工具卡片折叠 / 异步文件确认
- 事件经 SSE 推,前端原生 JS + EventSource

环境变量:
- TAISANG_MOCK_LLM=1  使用 MockLLM(测试用,返回固定回答)
- TAISANG_LLM_*  LLM 配置
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from ..agent_core.confirm import default_confirmer
from ..agent_core.events import (
    DEBUG_REQUEST,
    DEBUG_RESPONSE,
    DEBUG_TOOL_RESULT,
    FINAL_ANSWER,
    LLM_CHUNK,
    LLM_RETRY,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    USAGE_REPORT,
)
from ..agent_core.permission import CliPermissionManager
from ..agent_core.service import AgentService
from ..agent_core.trace import parent_span_id_var, span_id_var, trace_id_var
from ..config import load_config
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..session_memory.service import SessionMemoryService
from ..storage.paths import PathManager


def _normalize_path(path: str) -> Path:
    """规范化路径:展开 ~ + resolve。"""
    return Path(os.path.expanduser(path)).resolve()


class _SkipProactorConnectionLost(logging.Filter):
    """过滤 Windows asyncio Proactor _call_connection_lost 噪音日志。

    Windows ProactorEventLoop 在 socket/pipe 对端已关时,shutdown(SHUT_RDWR)
    抛 OSError,被 asyncio 内部吞成 ERROR 日志。不影响功能,只是刷屏。
    Linux/macOS SelectorEventLoop 无此问题。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "_call_connection_lost" not in record.getMessage()


def _setup_logging(level: str) -> None:
    """配 root logger level + 格式。

    level: 'debug' / 'info' / 'warning' / 'error'。
    session_memory logger 用 'session_memory' 名,INFO 级别能看到
    TRIGGER/STARTED/DONE/SKIPPED + forked agent 每轮 applied/denied 计数。
    日志格式带 [trace=xxx span=yyy],用 contextvar 贯穿一个 turn 的所有调用,
    没在 trace 上下文里的日志(启动/MCP 连接等)显示 [trace=-]。
    """
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    # 用 setLogRecordFactory 给所有 LogRecord 补 trace_id/span_id 字段。
    # 比 addFilter 更可靠:filter 加在 logger 上时,handler 仍可能 format
    # 未补字段的 record(如第三方库直接 handler.handle);RecordFactory 在
    # record 构造时就补,所有 handler 都能拿到。
    _record_factory = logging.getLogRecordFactory()

    def _factory(*args, **kwargs):
        record = _record_factory(*args, **kwargs)
        if not hasattr(record, "trace_id"):
            record.trace_id = trace_id_var.get()
        if not hasattr(record, "span_id"):
            record.span_id = span_id_var.get()
        if not hasattr(record, "parent_span_id"):
            record.parent_span_id = parent_span_id_var.get()
        return record

    logging.setLogRecordFactory(_factory)
    logging.basicConfig(
        level=level_map.get(level, logging.WARNING),
        format="%(asctime)s [%(levelname)s] [trace=%(trace_id)s span=%(span_id)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 过滤 Windows ProactorEventLoop _call_connection_lost 噪音:
    # socket/pipe 对端已关时 shutdown(SHUT_RDWR) 抛 OSError,被 asyncio 吞成 ERROR。
    # 不影响功能,Linux/macOS SelectorEventLoop 无此问题。
    if sys.platform == "win32":
        logging.getLogger("asyncio").addFilter(_SkipProactorConnectionLost())
    # 加日志落盘 ~/.taisang/logs/taisang.log (rotating 10MB × 5)。
    # 出问题/报 bug 时翻这个文件;不在 UI 暴露,普通用户无需感知。
    # 设 TAISANG_NO_FILE_LOG=1 可关闭(测试用,避免污染家目录)。
    _setup_file_logging(level_map.get(level, logging.WARNING))


def _setup_file_logging(level: int) -> None:
    """加 RotatingFileHandler 把日志落 ~/.taisang/logs/taisang.log。

    rotating 10MB × 5 份,最多占 ~50MB 磁盘。
    落盘失败(磁盘满/权限)只 log 一次 warning 到 stderr,不阻断启动。
    日志内容跟 stdout 完全一致,只是多一份持久化副本供排障/报 bug 用。
    文件日志带完整日期(stdout 只带时分秒),方便跨天排查。
    """
    if os.environ.get("TAISANG_NO_FILE_LOG") == "1":
        return

    from logging.handlers import RotatingFileHandler

    log_dir = Path.home() / ".taisang" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.getLogger(__name__).warning(
            "无法创建日志目录 %s,跳过文件日志: %s", log_dir, e
        )
        return

    log_file = log_dir / "taisang.log"
    try:
        handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
    except OSError as e:
        logging.getLogger(__name__).warning(
            "无法创建日志文件 %s,跳过文件日志: %s", log_file, e
        )
        return

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [trace=%(trace_id)s span=%(span_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)


def _make_llm():
    """根据环境决定用真 LLM 还是 MockLLM。"""
    if os.environ.get("TAISANG_MOCK_LLM") == "1":
        return MockLLM(
            [
                LLMResponse(text="(mock) 这个 repo 定义了 main 函数 [a.py:1]", tool_calls=[]),
            ]
            * 50
        )
    cfg = load_config()
    if not cfg.api_key:
        click.echo(
            "错误:未配置 LLM API key。请设置 TAISANG_LLM_API_KEY 环境变量,"
            "或写 ~/.taisang/settings.json。测试可用 TAISANG_MOCK_LLM=1。",
            err=True,
        )
        sys.exit(2)
    return LLMClient(cfg)


def _render_debug_request(payload: dict) -> None:
    """打印发给 LLM 的完整 messages + tools schema。"""
    import json as _json

    step = payload["step"]
    msgs = payload["messages"]
    tools = payload["tools"]
    click.echo(f"  [debug] === REQUEST step={step} ===")
    click.echo(f"  [debug] --- messages ({len(msgs)} 条) ---")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str) and len(content) > 300:
            content = content[:300] + f"... (+{len(content) - 300} chars)"
        tc = m.get("tool_calls")
        tc_str = f" tool_calls={_json.dumps(tc, ensure_ascii=False)[:200]}" if tc else ""
        tcid = m.get("tool_call_id")
        tcid_str = f" tool_call_id={tcid}" if tcid else ""
        click.echo(f"  [debug] [{i}] {role}: {content}{tc_str}{tcid_str}")
    click.echo(f"  [debug] --- tools ({len(tools)} 个) ---")
    for t in tools:
        click.echo(f"  [debug]   - {t.get('name', '?')}: {t.get('description', '')[:60]}")


def _render_debug_response(payload: dict) -> None:
    """打印 LLM 返回的 text + tool_calls。"""
    step = payload["step"]
    text = payload["text"]
    tool_calls = payload["tool_calls"]
    click.echo(f"  [debug] === RESPONSE step={step} ===")
    if text:
        preview = text if len(text) <= 300 else text[:300] + f"... (+{len(text) - 300} chars)"
        click.echo(f"  [debug] text: {preview}")
    else:
        click.echo("  [debug] text: (空)")
    if tool_calls:
        click.echo(f"  [debug] tool_calls ({len(tool_calls)} 个):")
        for tc in tool_calls:
            click.echo(
                f"  [debug]   id={tc.get('id', '?')} "
                f"name={tc['function']['name']} "
                f"args={tc['function'].get('arguments', '')}"
            )
    else:
        click.echo("  [debug] tool_calls: (无,这是最终答案)")


def _render_debug_tool_result(payload: dict) -> None:
    """打印工具执行的完整 observation(不截断)。"""
    step = payload["step"]
    name = payload["name"]
    obs = payload["observation"]
    click.echo(f"  [debug] === TOOL_RESULT step={step} name={name} ===")
    click.echo(f"  [debug] {obs}")


def _render_usage_report(payload: dict) -> None:
    """打印此轮 + session 累计 token + cache 命中率。

    cache.available=False 时打印 "N/A (endpoint 不报告)",不假装有数据。
    """
    turn = payload["turn"]
    session = payload["session"]
    cache = payload["cache"]
    click.echo(
        f"  [usage] 此轮: prompt={turn['prompt']} completion={turn['completion']} "
        f"total={turn['total']} | session 累计: prompt={session['prompt']} "
        f"completion={session['completion']} total={session['total']}"
    )
    if cache["available"]:
        # 当前 endpoint 不报告,这条分支暂不会触发;留作未来 endpoint 支持时用
        cached = cache.get("cached_tokens") or 0
        prompt = turn["prompt"] or 1
        hit_rate = cached / prompt * 100
        click.echo(f"  [usage] cache 命中率: {hit_rate:.1f}% (cached={cached}/{prompt})")
    else:
        click.echo("  [usage] cache 命中率: N/A (endpoint 不报告)")


@click.group()
def cli() -> None:
    """TaiSang - 简化版 coding agent。"""


@cli.command()
@click.option("--repo", default=".", help="工作目录(默认当前目录)")
@click.option(
    "--allow-dirs",
    multiple=True,
    help="允许 agent 访问的额外目录(可传多个)。--repo 自动加入允许列表。",
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="warning",
    help="日志级别(默认 warning,看 session memory 用 info)",
)
@click.option(
    "--dangerously-skip-permissions",
    is_flag=True,
    help="跳过所有权限检查和文件修改确认(危险!请自行承担风险)",
)
def chat(repo: str, allow_dirs: tuple[str, ...], log_level: str, dangerously_skip_permissions: bool) -> None:
    """进入交互式 coding agent。"""
    _setup_logging(log_level.lower())
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(f"错误:{source_root} 不是目录", err=True)
        sys.exit(1)
    allow_paths = [source_root] + [_normalize_path(d) for d in allow_dirs]

    if dangerously_skip_permissions:
        click.secho(
            "⚠️  --dangerously-skip-permissions 已启用:\n"
            "  - 目录访问不再询问\n"
            "  - 文件修改不再确认\n"
            "  - Bash 危险命令拦截已关闭\n"
            "请自行承担风险。",
            fg="red",
            bold=True,
        )

    llm = _make_llm()
    confirmer = default_confirmer  # 交互式 y/n
    session_mem = SessionMemoryService(
        llm=llm,
        memory_path=PathManager.session_memory_path("main"),
    )
    # 不在启动时 ensure_file:让 should_extract 的 init 分支(10000 token)
    # 自己创建笔记。extract worker 里有 ensure_file。

    # 启动时迁移旧 source_root/.taisang/sessions/ 到 ~/.taisang/sessions/
    PathManager.migrate_legacy_sessions(source_root)

    agent = AgentService(
        llm=llm,
        source_root=source_root,
        confirmer=confirmer,
        session_memory=session_mem,
        permission=CliPermissionManager(initial_dirs=allow_paths),
        allow_dirs=allow_paths,
        skip_permissions=dangerously_skip_permissions,
        session_id="main",
    )

    click.echo(f"taisang agent @ {source_root}")
    click.echo("输入 /exit 退出,/reset 清上下文,/debug 切换调试输出")

    debug_on = False
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
        if query == "/debug":
            debug_on = not debug_on
            agent.set_debug(debug_on)
            click.echo(f"(debug {'ON' if debug_on else 'OFF'})")
            continue

        def _render(evt) -> None:
            if evt.type == LLM_THINKING:
                click.echo("  [thinking]")
            elif evt.type == LLM_CHUNK:
                text_delta = evt.payload.get("text_delta", "")
                reasoning_delta = evt.payload.get("reasoning_delta", "")
                if text_delta:
                    click.echo(text_delta, nl=False)
                if reasoning_delta:
                    click.echo(click.style(reasoning_delta, fg="bright_black"), nl=False)
            elif evt.type == LLM_RETRY:
                p = evt.payload
                click.echo(click.style(f"  [重试 {p['attempt']}/{p.get('delay_sec', 0):.1f}s]", fg="yellow"))
            elif evt.type == TOOL_CALL:
                click.echo(f"  [tool] {evt.payload['name']} {evt.payload['args']}")
            elif evt.type == TOOL_RESULT:
                p = evt.payload
                click.echo(f"  [result] {p['name']} ({p['total_bytes']} bytes)")
            elif evt.type == FINAL_ANSWER:
                # 流式模式下 FINAL_ANSWER 不重复输出全文(已在 LLM_CHUNK 流完了)
                # 只换行 + 显示 [interrupted] 标记
                click.echo("")
                if evt.payload.get("interrupted"):
                    click.echo(click.style("  [interrupted]", fg="yellow"))
            elif evt.type == USAGE_REPORT:
                _render_usage_report(evt.payload)
            elif evt.type == DEBUG_REQUEST:
                _render_debug_request(evt.payload)
            elif evt.type == DEBUG_RESPONSE:
                _render_debug_response(evt.payload)
            elif evt.type == DEBUG_TOOL_RESULT:
                _render_debug_tool_result(evt.payload)

        try:
            answer = agent.run(query, on_event=_render)
        except KeyboardInterrupt:
            # Ctrl+C:run() 内部已 catch(set cancel_event + 转 InterruptedError)
            # 如果穿透到这里,说明 run() 已返回中断 Answer
            click.echo(click.style("\n  [interrupted]", fg="yellow"))
            continue
        if not answer.complete:
            click.echo(f"(incomplete: {answer.text})")


@cli.command()
@click.option("--repo", default="~", help="工作目录(默认家目录 ~)")
@click.option("--port", default=8765, help="HTTP 端口(默认 8765)")
@click.option("--host", default="127.0.0.1", help="绑定地址(默认 127.0.0.1,仅本机)")
@click.option(
    "--no-browser",
    is_flag=True,
    help="不自动开浏览器(默认会开)",
)
@click.option(
    "--allow-dirs",
    multiple=True,
    help="允许 agent 访问的额外目录(可传多个)。--repo 自动加入允许列表。",
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="warning",
    help="日志级别(默认 warning,看 session memory 用 info,排查问题用 debug)",
)
@click.option(
    "--dangerously-skip-permissions",
    is_flag=True,
    help="跳过所有权限检查和文件修改确认(危险!请自行承担风险)",
)
def web(
    repo: str,
    port: int,
    host: str,
    no_browser: bool,
    allow_dirs: tuple[str, ...],
    log_level: str,
    dangerously_skip_permissions: bool,
) -> None:
    """起本地 Web UI 服务(豆包风格),自动开浏览器。

    后端复用 AgentService 全部逻辑,前端单 HTML + SSE。
    浏览器访问 http://127.0.0.1:<port> 即可。
    """
    _setup_logging(log_level.lower())
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(f"错误:{source_root} 不是目录", err=True)
        sys.exit(1)
    allow_paths = [source_root] + [_normalize_path(d) for d in allow_dirs]

    if dangerously_skip_permissions:
        click.secho(
            "⚠️  --dangerously-skip-permissions 已启用:\n"
            "  - 目录访问不再询问\n"
            "  - 文件修改不再确认\n"
            "  - Bash 危险命令拦截已关闭\n"
            "请自行承担风险。",
            fg="red",
            bold=True,
        )

    try:
        from ..web.app import create_app
    except ImportError as e:
        click.echo(
            '错误:缺少 web 依赖。请先装:`pip install -e ".[web]"`(需要 fastapi + uvicorn)。',
            err=True,
        )
        click.echo(f"(细节: {e})", err=True)
        sys.exit(2)

    import uvicorn

    app = create_app(source_root, allow_dirs=allow_paths, skip_permissions=dangerously_skip_permissions)
    url = f"http://{host}:{port}"
    click.echo(f"taisang web UI @ {url}  (repo: {source_root})")
    click.echo("Ctrl+C 退出")
    if not no_browser:
        import threading
        import webbrowser

        # 延迟开浏览器,等服务起来
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())


if __name__ == "__main__":
    cli()
