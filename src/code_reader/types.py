"""核心数据类型。所有跨模块共享的数据结构集中在此,避免循环导入。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """答案中的引用。"""

    file: str
    line_range: tuple[int, int]
    symbol_id: str | None = None


class Answer(BaseModel):
    """Agent 最终回答。"""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    complete: bool = True  # False 表示因 max_steps/token 提前终止
    steps_used: int = 0
