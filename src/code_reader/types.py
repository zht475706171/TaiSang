"""核心数据类型。所有跨模块共享的数据结构集中在此,避免循环导入。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SymbolKind(StrEnum):
    """符号种类。"""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"


class Symbol(BaseModel):
    """一个代码符号(函数/类/方法等)。

    id 格式: "<file_path>::<qualified_name>",全局唯一。
    calls 是被调用符号的名字列表(best-effort,可能未解析到定义)。
    imports 是该符号所在文件 import 的模块名列表。
    """

    id: str
    kind: SymbolKind
    name: str
    file: str
    line_range: tuple[int, int]
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class RepoIndex(BaseModel):
    """一次索引的产物:AST 解析 + 跨文件调用图。"""

    source_root: str
    commit_hash: str
    symbols: list[Symbol]
    files: list[str]
    index_errors: list[dict[str, str]] = Field(default_factory=list)


class FileSummary(BaseModel):
    """文件级摘要(目标 100 字)。"""

    file: str
    summary: str
    symbol_ids: list[str] = Field(default_factory=list)


class ModuleSummary(BaseModel):
    """模块级摘要(目标 300 字,按目录聚合)。"""

    path: str  # 目录路径,根目录为 ""
    summary: str
    file_count: int


class GlobalSummary(BaseModel):
    """全局级摘要(目标 1000 字)。"""

    entry_points: list[str]
    core_modules: list[str]
    dependency_summary: str


class RepoMap(BaseModel):
    """三层摘要的完整产物。"""

    global_summary: GlobalSummary
    module_summaries: dict[str, ModuleSummary]
    file_summaries: dict[str, FileSummary]


class Snippet(BaseModel):
    """检索返回的片段。"""

    file: str
    line_range: tuple[int, int]
    text: str
    score: float
    symbol_id: str | None = None


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


class EntryPoint(BaseModel):
    """挖掘出的入口。"""

    symbol_id: str
    kind: str  # "cli" / "main" / "api_endpoint" / "test"
    description: str = ""


class MechanismCandidate(BaseModel):
    """核心机制候选(调用图指标筛出来的)。"""

    symbol_id: str
    name: str
    file: str
    in_degree: int  # 被多少符号调用
    cross_module_refs: int  # 跨模块引用数
    out_degree: int  # 它调用多少符号
    score: float  # 加权打分
    one_liner: str = ""  # LLM 给的一句话定位


class FlowCandidate(BaseModel):
    """关键流程候选(端到端调用链)。"""

    name: str  # 流程名(从入口 symbol 派生)
    entry_symbol_id: str
    chain: list[str]  # symbol_id 列表
    hop_count: int
    rendered: str  # 人话叙事(render_chain 输出)


class ModuleCandidate(BaseModel):
    """核心模块候选。"""

    path: str  # 目录路径
    file_count: int
    symbol_count: int
    in_degree: int  # 该模块所有符号被引用总和
    one_liner: str = ""


class Outline(BaseModel):
    """outliner 的完整产物。"""

    entry_points: list[EntryPoint]
    mechanism_candidates: list[MechanismCandidate]  # top 20
    flow_candidates: list[FlowCandidate]
    module_candidates: list[ModuleCandidate]
    selected_mechanisms: list[MechanismCandidate]  # LLM 选 5-10 个
