"""deepwriter 重点深挖测试。

覆盖:
- code_extractor 抽代码片段(含 context_lines 验证)
- DeepWriterService 写机制 / 流程 / 模块(prompt 内容断言 + 返回值断言)
"""

from code_reader.deepwriter.code_extractor import extract_code_snippet
from code_reader.deepwriter.service import DeepWriterService
from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.types import (
    FlowCandidate,
    MechanismCandidate,
    ModuleCandidate,
    RepoIndex,
    Symbol,
    SymbolKind,
)


class _CapturingLLM:
    """既能返回预设响应,又能捕获最后一次 chat 的 messages 的 mock。

    比 MockLLM 多一点:把最后一次 messages 暴露出来,供测试断言 prompt 内容。
    """

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_messages: list[dict] | None = None

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.last_messages = messages
        return LLMResponse(text=self.response_text, tool_calls=[])


def test_extract_code_snippet_returns_signature_and_body(tmp_path):
    """抽代码片段:返回带 [file:line] 标注 + 含 start_line-end_line 行内容。"""
    f = tmp_path / "a.py"
    f.write_text(
        "# 这是注释\n"
        "def foo(x):\n"
        "    y = x + 1\n"
        "    return y\n"
        "\n"
        "def bar():\n"
        "    pass\n",
        encoding="utf-8",
    )
    snippet = extract_code_snippet(f, "a.py", start_line=2, end_line=4)
    assert "def foo(x):" in snippet
    assert "return y" in snippet
    assert "[a.py:2-4]" in snippet


def test_extract_code_snippet_context_lines(tmp_path):
    """context_lines=3 时,前 3 行也被抽出来(带前导空格 marker)。"""
    f = tmp_path / "b.py"
    f.write_text(
        "line 1\n"
        "line 2\n"
        "line 3\n"
        "def target():\n"
        "    return 'hit'\n"
        "line 6\n"
        "line 7\n"
        "line 8\n",
        encoding="utf-8",
    )
    snippet = extract_code_snippet(f, "b.py", start_line=4, end_line=5, context_lines=3)
    # 前 3 行(1/2/3)应出现,且 marker 为 "  "(非目标行)
    assert "line 1" in snippet
    assert "line 2" in snippet
    assert "line 3" in snippet
    # 目标行 marker 为 ">>"
    assert ">>" in snippet
    # 标注头
    assert "[b.py:4-5]" in snippet


def test_deepwriter_write_mechanism(tmp_path):
    """write_mechanism:返回 LLM 响应文本,prompt 含机制名和代码片段标注。"""
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    return 42\n", encoding="utf-8")
    mock = MockLLM([LLMResponse(text="这是一个机制的讲解 [a.py:1-2]", tool_calls=[])])
    service = DeepWriterService(llm=mock, source_root=tmp_path)
    idx = RepoIndex(
        source_root=str(tmp_path),
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
    m = MechanismCandidate(
        symbol_id="a.py::foo",
        name="foo",
        file="a.py",
        in_degree=5,
        cross_module_refs=3,
        out_degree=2,
        score=20,
    )
    text = service.write_mechanism(idx, m)
    assert "机制" in text
    assert "a.py" in text
    # 断言 user prompt 含机制名 + 代码片段标注
    user_msg = mock.calls[0]["messages"][1]["content"]
    assert "foo" in user_msg
    assert "[a.py:1-2]" in user_msg


def test_deepwriter_write_flow(tmp_path):
    """write_flow:返回 LLM 响应,prompt 含 rendered_chain(chain 叙事)和链中 symbol 名。"""
    fa = tmp_path / "a.py"
    fa.write_text("def entry():\n    return 'in'\n", encoding="utf-8")
    fb = tmp_path / "b.py"
    fb.write_text("def worker():\n    return 'out'\n", encoding="utf-8")
    # 用 _CapturingLLM 同时断言返回值和 prompt 内容
    cap = _CapturingLLM("端到端流程讲解:entry -> worker [a.py:1-2]")
    service = DeepWriterService(llm=cap, source_root=tmp_path)
    idx = RepoIndex(
        source_root=str(tmp_path),
        commit_hash="x",
        symbols=[
            Symbol(
                id="a.py::entry",
                kind=SymbolKind.FUNCTION,
                name="entry",
                file="a.py",
                line_range=(1, 2),
                calls=["worker"],
                imports=[],
            ),
            Symbol(
                id="b.py::worker",
                kind=SymbolKind.FUNCTION,
                name="worker",
                file="b.py",
                line_range=(1, 2),
                calls=[],
                imports=[],
            ),
        ],
        files=["a.py", "b.py"],
        index_errors=[],
    )
    rendered = "entry (a.py:1-2) → worker (b.py:1-2)"
    f = FlowCandidate(
        name="entry_to_worker",
        entry_symbol_id="a.py::entry",
        chain=["a.py::entry", "b.py::worker"],
        hop_count=2,
        rendered=rendered,
    )
    text = service.write_flow(idx, f)
    # 返回值断言:含 chain 中某个 symbol 名 / file 引用
    assert "entry" in text or "worker" in text
    # prompt 断言:user 含 rendered_chain
    assert cap.last_messages is not None
    user_msg = cap.last_messages[1]["content"]
    assert rendered in user_msg
    # 也应含代码片段标注
    assert "[a.py:1-2]" in user_msg
    assert "[b.py:1-2]" in user_msg


def test_deepwriter_write_module(tmp_path):
    """write_module:返回 LLM 响应,prompt 含 module path 和 file_count。"""
    # 构造模块 auth 下的两个文件
    (tmp_path / "auth").mkdir()
    f1 = tmp_path / "auth" / "login.py"
    f1.write_text("def login():\n    return True\n", encoding="utf-8")
    f2 = tmp_path / "auth" / "logout.py"
    f2.write_text("def logout():\n    return False\n", encoding="utf-8")
    cap = _CapturingLLM("auth 模块讲解:负责登录登出")
    service = DeepWriterService(llm=cap, source_root=tmp_path)
    idx = RepoIndex(
        source_root=str(tmp_path),
        commit_hash="x",
        symbols=[
            Symbol(
                id="auth/login.py::login",
                kind=SymbolKind.FUNCTION,
                name="login",
                file="auth/login.py",
                line_range=(1, 2),
                calls=[],
                imports=[],
            ),
            Symbol(
                id="auth/logout.py::logout",
                kind=SymbolKind.FUNCTION,
                name="logout",
                file="auth/logout.py",
                line_range=(1, 2),
                calls=[],
                imports=[],
            ),
        ],
        files=["auth/login.py", "auth/logout.py"],
        index_errors=[],
    )
    m = ModuleCandidate(
        path="auth",
        file_count=2,
        symbol_count=2,
        in_degree=5,
        one_liner="登录登出模块",
    )
    text = service.write_module(idx, m)
    assert "auth" in text
    # prompt 断言:user 含 module path 和 file_count
    assert cap.last_messages is not None
    user_msg = cap.last_messages[1]["content"]
    assert "auth" in user_msg
    assert "2" in user_msg  # file_count
    # 也应含模块下 symbol 的 id
    assert "auth/login.py::login" in user_msg
