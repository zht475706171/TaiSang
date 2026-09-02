"""ConversationStore 单元测试:jsonl append + load_all + meta.json 原子写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from taisang.storage.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    sessions_dir = tmp_path / ".taisang" / "sessions"
    sessions_dir.mkdir(parents=True)
    return ConversationStore(session_id="abc12345", sessions_dir=sessions_dir)


def test_append_and_load_all_roundtrip(store: ConversationStore) -> None:
    """append 3 条 record 后 load_all 返回同样的 3 条(dict 相等)。"""
    r1 = {"type": "user", "role": "user", "content": "你好", "uuid": "u1", "timestamp": 1.0}
    r2 = {"type": "assistant", "role": "assistant", "content": "你好!", "uuid": "a1", "timestamp": 1.1}
    r3 = {"type": "tool", "role": "tool", "name": "read_file", "content": "x", "tool_call_id": "t1", "uuid": "t1", "timestamp": 1.2}

    store.append(r1)
    store.append(r2)
    store.append(r3)

    loaded = store.load_all()
    assert len(loaded) == 3
    assert loaded[0] == r1
    assert loaded[1] == r2
    assert loaded[2] == r3