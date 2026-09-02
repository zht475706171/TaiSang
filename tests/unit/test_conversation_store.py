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


def test_load_all_skips_corrupt_lines(store: ConversationStore) -> None:
    """jsonl 里有损坏行(非法 JSON)时跳过,返回能解析的行。"""
    r1 = {"type": "user", "role": "user", "content": "ok", "uuid": "u1", "timestamp": 1.0}
    store.append(r1)
    # 手动追加一行损坏的
    with open(store.jsonl_path, "a", encoding="utf-8") as f:
        f.write("{this is not json\n")
    r3 = {"type": "user", "role": "user", "content": "ok2", "uuid": "u2", "timestamp": 2.0}
    store.append(r3)

    loaded = store.load_all()
    assert len(loaded) == 2
    assert loaded[0] == r1
    assert loaded[1] == r3


def test_load_all_file_not_exists(tmp_path: Path) -> None:
    """jsonl 不存在时(新建会话)load_all 返回 []。"""
    sessions_dir = tmp_path / ".taisang" / "sessions"
    sessions_dir.mkdir(parents=True)
    store = ConversationStore(session_id="nonexist", sessions_dir=sessions_dir)
    # 不调 append,文件不存在
    assert store.load_all() == []