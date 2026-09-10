"""apply-tool-result-budget——上下文管理三道流水线第一道。

单轮 tool_result 总字节数超预算时,把最大的几条持久化到磁盘,
原 content 替换成含 preview 的占位符;决策跨 turn 冻结。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContentReplacementState:
    """跨 turn 持有替换决策。决策一旦做出,冻结。

    - seen_ids: 已决策过的 tool_use_id 集合(下次再见到直接复用决策,不再 I/O)
    - replacements: tool_use_id → 已生成的 preview 占位字符串
    """

    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)


# 预算:单轮 tool_result 总和上限(字节)
PER_MESSAGE_BUDGET_BYTES = 200_000
# 单条 tool_result 持久化阈值
DEFAULT_PERSIST_THRESHOLD = 50_000
# preview 截断字节数
PREVIEW_BYTES = 2000
# 跳过 budget 的工具名(小结果或本身是写操作)
SKIP_TOOL_NAMES = {"write_doc", "list_pending_sections", "finalize_doc", "glob"}

CLEARED_PLACEHOLDER = (
    "[persisted-output]\n"
    "完整输出已写入 {path} ({size} 字节)\n"
    "这里是预览:\n{preview}\n"
    "[... {omitted} 字节省略,见文件 ...]\n"
    "[/persisted-output]"
)


def enforce_budget(
    messages: list[dict],
    state: ContentReplacementState,
    persist_dir: Path,
    budget_bytes: int = PER_MESSAGE_BUDGET_BYTES,
    persist_threshold: int = DEFAULT_PERSIST_THRESHOLD,
    tool_size_limits: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """对 messages 跑 apply-tool-result-budget。

    返回 (新 messages, 本次新做的替换决策列表)。

    三分区:
    - mustReapply:已在 seen_ids,套已存的 preview(若有)即可,无 I/O
    - frozen/skip:在 SKIP_TOOL_NAMES 或 max_result_size_chars=Infinity(Read opt-out),标记 seen 不替换
    - fresh:累加字节;若超预算,按"最大优先"持久化直到降到预算内

    tool_size_limits: tool_name → max_result_size_chars 映射。
        - None 或未列出的 tool:默认 100_000(参与持久化)
        - float("inf"):opt-out 永不持久化(Read 工具,读回文件是循环)
    """
    new_messages = list(messages)
    newly_replaced: list[dict] = []
    # 找所有 tool message
    tool_indices = [i for i, m in enumerate(new_messages) if m["role"] == "tool"]
    fresh_to_check: list[int] = []
    total_bytes = 0
    limits = tool_size_limits or {}
    for i in tool_indices:
        tcid = new_messages[i].get("tool_call_id", "")
        content = new_messages[i].get("content", "")
        if not isinstance(content, str):
            continue
        if tcid in state.seen_ids:
            # mustReapply:套已存的 preview
            if tcid in state.replacements:
                new_messages[i] = {**new_messages[i], "content": state.replacements[tcid]}
            # frozen 但没替换的:不动
            continue
        # fresh
        name = new_messages[i].get("name", "")
        # 跳过条件:SKIP_TOOL_NAMES 白名单 OR max_result_size_chars=Infinity(Read opt-out)
        tool_limit = limits.get(name, 100_000)
        if name in SKIP_TOOL_NAMES or tool_limit == float("inf"):
            state.seen_ids.add(tcid)
            continue
        fresh_to_check.append(i)
        total_bytes += len(content.encode("utf-8"))
    if total_bytes <= budget_bytes:
        # 没超预算,所有 fresh 标记为 seen(frozen,不替换)
        for i in fresh_to_check:
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
        return new_messages, []
    # 超预算:fresh 里按"最大优先"持久化,直到总字节 < budget
    fresh_to_check.sort(
        key=lambda i: len(new_messages[i].get("content", "").encode("utf-8")),
        reverse=True,
    )
    bytes_to_free = total_bytes - budget_bytes
    for i in fresh_to_check:
        if bytes_to_free <= 0:
            break
        content = new_messages[i].get("content", "")
        content_bytes = len(content.encode("utf-8"))
        if content_bytes < persist_threshold:
            # 不够大,不值得持久化
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
            continue
        # 持久化到磁盘
        tcid = new_messages[i].get("tool_call_id", "")
        persist_file = persist_dir / f"{tcid}.txt"
        persist_file.write_text(content, encoding="utf-8")
        # preview 按字符切(PREVIEW_BYTES 近似字符数,作为简化版可接受)
        preview = content[:PREVIEW_BYTES]
        omitted = content_bytes - PREVIEW_BYTES
        placeholder = CLEARED_PLACEHOLDER.format(
            path=str(persist_file),
            size=f"{content_bytes:,}",
            preview=preview,
            omitted=f"{omitted:,}",
        )
        state.replacements[tcid] = placeholder
        state.seen_ids.add(tcid)
        new_messages[i] = {**new_messages[i], "content": placeholder}
        newly_replaced.append({"tool_call_id": tcid, "path": str(persist_file)})
        bytes_to_free -= content_bytes
    # 剩下的 fresh 标记为 frozen 不替换
    for i in fresh_to_check:
        tcid = new_messages[i].get("tool_call_id", "")
        if tcid not in state.seen_ids:
            state.seen_ids.add(tcid)
    return new_messages, newly_replaced
