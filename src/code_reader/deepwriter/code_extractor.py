"""代码片段抽取:给 LLM 喂带行号标注的目标代码片段。"""

from __future__ import annotations

from pathlib import Path


def extract_code_snippet(
    file_path: Path,
    rel_path: str,
    start_line: int,
    end_line: int,
    context_lines: int = 3,
) -> str:
    """抽代码片段:context_lines 行前文 + start_line-end_line + 标注行号。

    Args:
        file_path: 文件绝对路径。
        rel_path: 相对路径(用于标注头)。
        start_line: 目标起始行(1-based)。
        end_line: 目标结束行(1-based,含)。
        context_lines: 上下文行数,前后各取 context_lines 行。

    Returns:
        形如:
            [rel_path:start-end]
              <ctx_line_no>  <code>
            >> <target_line_no>  <code>
            ...
    """
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    ctx_start = max(0, start_line - 1 - context_lines)
    ctx_end = min(len(lines), end_line + context_lines)
    parts: list[str] = []
    parts.append(f"[{rel_path}:{start_line}-{end_line}]")
    for i in range(ctx_start, ctx_end):
        marker = ">>" if start_line <= i + 1 <= end_line else "  "
        parts.append(f"{marker} {i + 1:4d}  {lines[i]}")
    return "\n".join(parts)
