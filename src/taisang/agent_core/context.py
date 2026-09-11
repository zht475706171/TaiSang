"""Agent 上下文管理 + compaction。

Task 12 重写:
- token 估算改用 tiktoken 真 token 计数(cl100k_base)
- 追加 replace_messages() 给 autocompact 整体替换用
- 保留旧 compact()(向后兼容 test_context.py 5 个测试,Task 8 加的)

旧 compact() 策略(从 claude-code 抄的简化版):
- token 预算逼近时触发 compact
- 旧 tool_result 压成一行摘要 "[compacted: tool=X, Y chars]"
- 保留最近 N 条 tool_result
"""

from __future__ import annotations

from typing import Callable

import tiktoken

from .context_window import get_autocompact_threshold


class ContextManager:
    """管理 messages 列表 + token 估算。

    token 估算用 tiktoken(cl100k_base)的真实编码器;
    若 tiktoken 不可用(极少数离线环境),fallback 到 len//3 粗估。

    autocompact 阈值对齐 claude-code:
    threshold = effective_window - buffer
    effective_window = token_budget - reserved_for_summary
    (context_window.py 封装了公式,token_budget 即 context_window)
    """

    # 模块级缓存 tiktoken 编码器(避免重复加载)
    _enc: tiktoken.Encoding | None = None

    def __init__(
        self,
        token_budget: int = 200_000,  # 默认 200K(对齐 claude-code MODEL_CONTEXT_WINDOW_DEFAULT)
        keep_recent: int = 4,  # compact 时保留最近 N 条 tool_result
        on_append: "Callable[[dict], None] | None" = None,
    ) -> None:
        self.token_budget = token_budget
        self.keep_recent = keep_recent
        self._messages: list[dict] = []
        self.on_append = on_append
        # 真 token 计数器(懒加载,首次用时初始化)
        if ContextManager._enc is None:
            try:
                ContextManager._enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                ContextManager._enc = None

    def estimate_tokens(self, text: str) -> int:
        """用 tiktoken 真 token 计数;不可用 fallback 到 3 char/token 近似。

        取 tiktoken 真值与 char//3 的较大者:真实文本 tiktoken 真值通常 > char//3,
        退化场景(如 "x"*4000 这种 BPE 会合并的重复串)由 char//3 兜底,
        保证 should_compact 在长内容上仍能触发(向后兼容 test_context.py)。
        """
        if not text:
            return 0
        char_based = max(1, len(text) // 3)
        if ContextManager._enc is not None:
            try:
                tk = len(ContextManager._enc.encode(text))
            except Exception:
                tk = 0
            return max(tk, char_based)
        # fallback:旧版粗估(保留以防 tiktoken 离线包不可用)
        return char_based

    def _msg_tokens(self, msg: dict) -> int:
        content = msg.get("content", "")
        if isinstance(content, str):
            return self.estimate_tokens(content)
        return 0

    def total_tokens(self) -> int:
        return sum(self._msg_tokens(m) for m in self._messages)

    def should_compact(self) -> bool:
        # 阈值对齐 claude-code:
        # threshold = effective_window - buffer
        # effective_window = token_budget - reserved_for_summary
        # (token_budget 即 context_window,由 AgentService 解析后传入)
        threshold = get_autocompact_threshold(self.token_budget)
        return self.total_tokens() > threshold

    def append_system(self, text: str) -> None:
        msg = {"role": "system", "content": text}
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

    def replace_system_prompt(self, text: str) -> None:
        """原地替换第一个 system 消息的 content。

        无 system 消息时 no-op(不主动插入)。
        用于 prompt 配置变更后广播到活跃 session。
        """
        for msg in self._messages:
            if msg["role"] == "system":
                msg["content"] = text
                break

    def append_user(self, text: str) -> None:
        msg = {"role": "user", "content": text}
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

    def append_assistant(self, text: str, tool_calls: list[dict] | None = None) -> None:
        msg = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

    def append_tool_result(self, text: str, name: str, tool_call_id: str | None = None) -> None:
        msg = {
            "role": "tool",
            "name": name,
            "content": text,
            "tool_call_id": tool_call_id or name,
        }
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

    def messages(self) -> list[dict]:
        return list(self._messages)

    def replace_messages(
        self,
        new_messages: list[dict],
        compaction_via: str | None = None,
    ) -> None:
        """整体替换 messages。

        compaction_via 非 None 时(autocompact 触发):先写一条 system boundary
        record 到 on_append,再把 new_messages 逐条写到 on_append。这是压缩边界,
        resume 时读到这条知道这里压缩过(UI 显示分隔符,灌回 ctx 时跳过)。

        compaction_via=None 时(如 enforce_budget 路径):只替换内存,不写 on_append
        (避免每次 run 循环都重复写盘;enforce_budget 的替换是瞬态优化,不需要持久化)。
        """
        if self.on_append and compaction_via:
            self.on_append({"role": "system", "content": f"[compacted via {compaction_via}]"})
            for msg in new_messages:
                self.on_append(msg)
        self._messages = list(new_messages)

    def load_from_records(self, records: list[dict]) -> None:
        """resume 灌回专用:从 jsonl records 重建内存 _messages。

        - 截断式 resume:找到最后一条 compacted boundary record(role=system
          且 content 以 [compacted 开头),只灌回 boundary 之后的 records。
          boundary 之前的内容已被压缩成后面的 summary,boundary 后的 records
          就是压缩后快照。无 boundary(从未压缩过)则灌回全部。
        - system prompt 不从 jsonl 灌回:保留 __init__ 时 append_system 写入的最新
          system(已在 self._messages[0]),跳过 truncated 里所有 role=system 的 record
          (包括 boundary 标记、旧 system、重启时重复 append 的 system)。
          原因:system 是可重建的配置类内容(人设+工具+skill+mcp+agents+画像),
          应该用当前最新的,不该用 jsonl 里可能过期的旧版本。这也修了"autocompact 后
          resume 丢 system"的坑——boundary 后的 system 是 19 字符标记,灌回会覆盖掉
          __init__ 建的完整 system。
        - 直接赋值 _messages,不走 on_append(避免重复写盘)。

        用于 SessionRegistry.get_or_load lazy 重建时,把磁盘 jsonl 灌回内存 ctx。
        """
        last_boundary_idx = -1
        for i, r in enumerate(records):
            if (r.get("role") == "system"
                    and isinstance(r.get("content"), str)
                    and r["content"].startswith("[compacted")):
                last_boundary_idx = i
        truncated = list(records[last_boundary_idx + 1:])
        # 保留 __init__ 时建的最新 system(已在 self._messages),
        # 只灌回 truncated 里的非 system 消息(user/assistant/tool)。
        # jsonl 里的 system 全跳过:boundary 标记、旧 system、重启重复 append 的 system。
        new_messages = [m for m in self._messages if m.get("role") == "system"]
        for r in truncated:
            if r.get("role") != "system":
                new_messages.append(r)
        self._messages = new_messages

    # NOTE:旧 compact() 保留(向后兼容 test_context.py 5 个测试)。
    # Task 12 的新版 AgentService 不再调本方法,改用 enforce_budget + autocompact。
    def compact(self) -> None:
        """压缩旧 tool_result,保留 system + 最近 N 条。

        旧版逻辑(保留给 test_context.py 用):
        - 找所有 tool message
        - 除最近 N 条外,旧的压成 "[compacted: tool=X, Y chars]"
        - 循环压,直到 token 够用或无可压
        """
        tool_idx = [i for i, m in enumerate(self._messages) if m["role"] == "tool"]
        if len(tool_idx) <= self.keep_recent:
            return
        to_compact_idx = tool_idx[: -self.keep_recent]
        for i in to_compact_idx:
            m = self._messages[i]
            old_text = m.get("content", "")
            if isinstance(old_text, str) and not old_text.startswith("[compacted"):
                m["content"] = f"[compacted: tool={m.get('name')}, {len(old_text)} chars]"
        # 循环压,直到 token 够用
        while self.total_tokens() > self.token_budget and any(
            isinstance(m.get("content"), str) and not m.get("content", "").startswith("[compacted")
            for m in self._messages
            if m["role"] == "tool"
        ):
            for _i, m in enumerate(self._messages):
                if m["role"] != "tool":
                    continue
                content = m.get("content", "")
                if isinstance(content, str) and not content.startswith("[compacted"):
                    m["content"] = f"[compacted: tool={m.get('name')}, {len(content)} chars]"
                    break
            else:
                break
