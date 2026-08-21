"""Python tree-sitter parser。

用 tree-sitter 解析 Python 文件,抽出 Symbol 列表(函数/类/方法)。
容错:遇到语法错误不抛异常,返回能抽到的部分(可能为空)。
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from ..types import Symbol, SymbolKind

_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_LANGUAGE)


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _extract_calls(body_node, source: bytes) -> list[str]:
    """从函数体里抽所有 call 芃点,返回被调用函数名列表。

    嵌套 call(比如 print(greet(name)))也会被抓:pop call 时记录 function 名,
    然后继续深入其子节点找嵌套 call(每个 call 节点唯一,不会重复)。
    """
    calls: list[str] = []
    stack = [body_node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                name = _node_text(fn, source)
                # 只取最末段(比如 self.foo 取 foo,obj.bar 取 bar)
                if "." in name:
                    name = name.split(".")[-1]
                calls.append(name)
            # 继续深入子节点,抓嵌套 call(如 print(greet(name)) 里的 greet)
        for child in n.children:
            stack.append(child)
    return calls


def _extract_imports(root_node, source: bytes) -> list[str]:
    """从文件根抽 import 的模块名。"""
    imports: list[str] = []
    for child in root_node.children:
        if child.type == "import_statement":
            # import os / import os.path → 取 os
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                imports.append(name.split(".")[0])
        elif child.type == "import_from_statement":
            module_node = child.child_by_field_name("module_name")
            if module_node:
                name = _node_text(module_node, source)
                imports.append(name.split(".")[0])
    return imports


def _make_symbol_id(file_rel: str, name: str, parent: str | None) -> str:
    qual = f"{parent}.{name}" if parent else name
    return f"{file_rel}::{qual}"


def _walk_functions_and_classes(root_node, source: bytes, file_rel: str, imports: list[str]):
    """遍历 AST,产出 Symbol。class 内的 method 标 METHOD,parent 为 class 名。"""
    symbols: list[Symbol] = []

    def visit(node, parent_class: str | None):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _node_text(name_node, source)
            body = node.child_by_field_name("body")
            calls = _extract_calls(body, source) if body else []
            kind = SymbolKind.METHOD if parent_class else SymbolKind.FUNCTION
            symbols.append(
                Symbol(
                    id=_make_symbol_id(file_rel, name, parent_class),
                    kind=kind,
                    name=name,
                    file=file_rel,
                    line_range=(node.start_point[0] + 1, node.end_point[0] + 1),
                    calls=calls,
                    imports=imports,
                )
            )
            # 函数内可能嵌套函数(不深入 method 体的 call,已经在 _extract_calls 里抓了)
            for child in node.children:
                if child.type == "function_definition":
                    visit(child, parent_class)
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _node_text(name_node, source)
            symbols.append(
                Symbol(
                    id=_make_symbol_id(file_rel, name, parent_class),
                    kind=SymbolKind.CLASS,
                    name=name,
                    file=file_rel,
                    line_range=(node.start_point[0] + 1, node.end_point[0] + 1),
                    calls=[],
                    imports=imports,
                )
            )
            # 进入 class body 找 method
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    visit(child, parent_class=name)
            return  # 不再深入 class 的其他子节点
        else:
            for child in node.children:
                visit(child, parent_class)

    visit(root_node, None)
    return symbols


def parse_file(path: Path, rel_path: str | None = None) -> list[Symbol]:
    """解析单个 Python 文件,返回 Symbol 列表。

    rel_path 是相对 repo 根的路径,用于 Symbol.file 和 id。
    如果不传,用 path.name。
    容错:语法错误不抛异常,返回空列表或部分符号。
    """
    file_rel = rel_path or path.name
    try:
        source = path.read_bytes()
    except OSError:
        return []
    try:
        tree = _PARSER.parse(source)
    except Exception:
        return []
    root = tree.root_node
    imports = _extract_imports(root, source)
    return _walk_functions_and_classes(root, source, file_rel, imports)
