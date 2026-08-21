"""测试 Python tree-sitter parser。"""

from pathlib import Path

from code_reader.indexer.parser_python import parse_file
from code_reader.types import SymbolKind

FIXTURES = Path(__file__).parent.parent / "fixtures" / "python"


def test_parse_simple_file_extracts_functions():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    names = {s.name for s in symbols}
    assert "greet" in names
    assert "main" in names


def test_parse_simple_file_function_kind():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    greet = next(s for s in symbols if s.name == "greet")
    assert greet.kind == SymbolKind.FUNCTION
    assert greet.file.endswith("sample_simple.py")
    # line_range 是 (start, end),从 1 开始
    assert greet.line_range[0] >= 5  # greet 在第 6 行附近
    assert greet.line_range[1] > greet.line_range[0]


def test_parse_simple_file_extracts_calls():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    main = next(s for s in symbols if s.name == "main")
    # main 里调用了 greet, os.environ.get, print, Path
    assert "greet" in main.calls
    assert "print" in main.calls


def test_parse_simple_file_extracts_imports():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    # imports 算在文件级,这里用第一个符号的 imports 代表文件 imports
    assert any("os" in s.imports for s in symbols)
    assert any("pathlib" in s.imports for s in symbols)


def test_parse_class_extracts_methods():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    names = {s.name for s in symbols}
    assert "Stack" in names  # class 本身也是 symbol
    assert "push" in names
    assert "pop" in names
    assert "__init__" in names


def test_parse_class_method_kind():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    push = next(s for s in symbols if s.name == "push")
    assert push.kind == SymbolKind.METHOD


def test_parse_class_method_calls():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    use_stack = next(s for s in symbols if s.name == "use_stack")
    assert "Stack" in use_stack.calls  # 构造调用
    assert "push" in use_stack.calls


def test_parse_syntax_error_does_not_crash():
    """容错解析:语法错误文件不抛异常,返回可能为空或部分符号。"""
    symbols = parse_file(FIXTURES / "sample_with_syntax_error.py")
    # 只要不抛异常就算过,符号列表可以为空
    assert isinstance(symbols, list)


def test_parse_symbol_id_unique_and_qualified():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    ids = {s.id for s in symbols}
    # id 格式: "<file>::<name>",全唯一
    assert len(ids) == len(symbols)
    for sid in ids:
        assert "::" in sid
