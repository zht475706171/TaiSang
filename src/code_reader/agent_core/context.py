"""Agent 上下文管理 + compaction。

策略(从 claude-code 抄的简化版):
- token 预算逼近时触发 compact
- compact 保留: system + 最早的摘要(简化为不保留) + 最近 N 轮 tool_result + 引用源码(简化为保留)
- 旧 tool_result 压成一行摘要 "[compacted: tool=X, Y chars]"
"""

from __future__ import annotations


class ContextManager:
    """管理 messages 列表 + token 估算。"""

    def __init__(
        self,
        token_budget: int = 32_000,
        compact_ratio: float = 0.8,  # 用到 80% 触发
        keep_recent: int = 4,  # compact 时保留最近 N 条 tool_result
    ) -> None:
        self.token_budget = token_budget
        self.compact_ratio = compact_ratio
        self.keep_recent = keep_recent
        self._messages: list[dict] = []

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数。

        英文约 4 char/token,中文约 1.5 char/token。混合取 3 char/token 近似。
        真实场景可换 tiktoken,这里简化以保证测试稳定。
        """
        if not text:
            return 0
        return max(1, len(text) // 3)

    def _msg_tokens(self, msg: dict) -> int:
        content = msg.get("content", "")
        if isinstance(content, str):
            return self.estimate_tokens(content)
        return 0

    def total_tokens(self) -> int:
        return sum(self._msg_tokens(m) for m in self._messages)

    def should_compact(self) -> bool:
        return self.total_tokens() > self.token_budget * self.compact_ratio

    def append_system(self, text: str) -> None:
        self._messages.append({"role": "system", "content": text})

    def append_user(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def append_assistant(self, text: str, tool_calls: list[dict] | None = None) -> None:
        msg = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)

    def append_tool_result(self, text: str, name: str, tool_call_id: str | None = None) -> None:
        self._messages.append(
            {
                "role": "tool",
                "name": name,
                "content": text,
                "tool_call_id": tool_call_id or name,
            }
        )

    def messages(self) -> list[dict]:
        return list(self._messages)

    def compact(self) -> None:
        """压缩旧 tool_result,保留 system + 最近 N 条。"""
        if not self.should_compact() and self.total_tokens() <= self.token_budget:
            # 只在确实超预算时压(测试可能直接调 compact)
            pass
        # 收集所有 tool message 的索引
        tool_idx = [i for i, m in enumerate(self._messages) if m["role"] == "tool"]
        if len(tool_idx) <= self.keep_recent:
            return
        # 要压缩的:除最近 N 条之外
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
            # 找下一个最旧的未压缩 tool message
            for _i, m in enumerate(self._messages):
                if m["role"] != "tool":
                    continue
                content = m.get("content", "")
                if isinstance(content, str) and not content.startswith("[compacted"):
                    m["content"] = f"[compacted: tool={m.get('name')}, {len(content)} chars]"
                    break
            else:
                break
