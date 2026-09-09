"""测试 CommandRegistry:render / $ARGUMENTS 替换 / disabled / not found。"""

from pathlib import Path

from taisang.commands.registry import CommandRegistry
from taisang.commands.types import Command


def _make_cmd(
    name: str = "commit",
    content: str = "git status\n$ARGUMENTS\n",
    allowed_tools: list[str] | None = None,
    disabled: bool = False,
) -> Command:
    return Command(
        name=name,
        description="test",
        argument_hint="",
        allowed_tools=allowed_tools,
        content=content,
        file_path=Path("/tmp/test.md"),
        source="user",
        disabled=disabled,
    )


def test_render_replaces_arguments_placeholder() -> None:
    """render 把 $ARGUMENTS 替换成用户传入的 args。"""
    reg = CommandRegistry([_make_cmd(content="do $ARGUMENTS now")])
    rendered = reg.render("commit", "fix typo")
    assert rendered is not None
    assert "do fix typo now" in rendered
    assert "$ARGUMENTS" not in rendered


def test_render_empty_args_replaces_with_empty() -> None:
    """args 为空时 $ARGUMENTS 替换成空串。"""
    reg = CommandRegistry([_make_cmd(content="do $ARGUMENTS")])
    rendered = reg.render("commit", "")
    assert rendered is not None
    assert "do " in rendered
    assert "$ARGUMENTS" not in rendered


def test_render_includes_command_header() -> None:
    """render 正文含 # Command: <name> 标题。"""
    reg = CommandRegistry([_make_cmd(name="commit")])
    rendered = reg.render("commit", "")
    assert "# Command: commit" in rendered


def test_render_allowed_tools_header() -> None:
    """allowed_tools 非空时,正文前加提示段。"""
    reg = CommandRegistry([_make_cmd(allowed_tools=["Bash", "read_file"])])
    rendered = reg.render("commit", "")
    assert "只允许使用以下工具: Bash, read_file" in rendered


def test_render_allowed_tools_none_no_header() -> None:
    """allowed_tools 为 None 时,不加提示段。"""
    reg = CommandRegistry([_make_cmd(allowed_tools=None)])
    rendered = reg.render("commit", "")
    assert "只允许使用" not in rendered


def test_render_not_found_returns_none() -> None:
    """不存在的 command → None。"""
    reg = CommandRegistry([_make_cmd(name="commit")])
    assert reg.render("nonexistent", "") is None


def test_render_disabled_returns_none() -> None:
    """disabled command → render 返回 None(等效于不存在)。"""
    reg = CommandRegistry([_make_cmd(disabled=True)])
    assert reg.render("commit", "") is None
    assert reg.get("commit") is None


def test_get_returns_command_when_enabled() -> None:
    """get 对 enabled command 返回 Command 对象。"""
    c = _make_cmd()
    reg = CommandRegistry([c])
    got = reg.get("commit")
    assert got is not None
    assert got.name == "commit"


def test_list_enabled_excludes_disabled() -> None:
    """list_enabled 只列 enabled。"""
    reg = CommandRegistry([
        _make_cmd(name="a", disabled=False),
        _make_cmd(name="b", disabled=True),
    ])
    enabled = reg.list_enabled()
    assert {c.name for c in enabled} == {"a"}


def test_list_all_includes_disabled() -> None:
    """list_all 含 disabled(管理 UI 用)。"""
    reg = CommandRegistry([
        _make_cmd(name="a", disabled=False),
        _make_cmd(name="b", disabled=True),
    ])
    all_cmds = reg.list_all()
    assert {c.name for c in all_cmds} == {"a", "b"}