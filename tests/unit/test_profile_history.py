from __future__ import annotations

import json

import pytest

from taisang.user_profile.history import (
    append_profile_change,
    read_profile_history,
    rollback_profile,
)


def test_append_and_read_history(tmp_path):
    """追加 + 读历史。"""
    hp = tmp_path / "history.jsonl"
    append_profile_change(
        field="content",
        old="",
        new="### 技术栈\nPython",
        source="user",
        session_id=None,
        snapshot_before={"content": ""},
        history_path=hp,
    )
    records = read_profile_history(hp)
    assert len(records) == 1
    assert records[0]["field"] == "content"
    assert records[0]["new"] == "### 技术栈\nPython"
    assert records[0]["source"] == "user"


def test_history_keeps_latest_5(tmp_path):
    """超过 5 条,删最老的(滚动窗口)。"""
    hp = tmp_path / "history.jsonl"
    for i in range(7):
        append_profile_change(
            field="content",
            old=str(i),
            new=str(i + 1),
            source="user",
            session_id=None,
            snapshot_before={"content": str(i)},
            history_path=hp,
        )
    records = read_profile_history(hp)
    assert len(records) == 5
    # 最老的应是 new="3" 那条(0/1/2 被删)
    assert records[0]["new"] == "3"
    assert records[-1]["new"] == "7"


def test_history_includes_snapshot_before(tmp_path):
    """每条带 snapshot_before 完整快照。"""
    hp = tmp_path / "history.jsonl"
    append_profile_change(
        field="content",
        old="### 技术栈\nPython",
        new="### 技术栈\nGo",
        source="agent",
        session_id="abc123",
        snapshot_before={"content": "### 技术栈\nPython"},
        history_path=hp,
    )
    records = read_profile_history(hp)
    assert records[0]["snapshot_before"]["content"] == "### 技术栈\nPython"
    assert records[0]["session_id"] == "abc123"


def test_history_missing_file_returns_empty(tmp_path):
    """历史文件不存在 → 空列表。"""
    hp = tmp_path / "nope.jsonl"
    assert read_profile_history(hp) == []


def test_history_corrupt_line_skipped(tmp_path):
    """损坏行跳过,不阻塞读。"""
    hp = tmp_path / "history.jsonl"
    rec1 = json.dumps(
        {
            "ts": "x",
            "source": "user",
            "field": "content",
            "old": "",
            "new": "Python",
            "session_id": None,
            "snapshot_before": {"content": ""},
        }
    )
    rec2 = json.dumps(
        {
            "ts": "y",
            "source": "user",
            "field": "content",
            "old": "Python",
            "new": "Go",
            "session_id": None,
            "snapshot_before": {"content": "Python"},
        }
    )
    hp.write_text(
        rec1 + "\n" "THIS IS NOT JSON\n" + rec2 + "\n",
        encoding="utf-8",
    )
    records = read_profile_history(hp)
    assert len(records) == 2  # 损坏行跳过


def test_rollback_uses_last_snapshot_before(tmp_path):
    """回滚用最后一条 snapshot_before。"""
    hp = tmp_path / "history.jsonl"
    append_profile_change(
        field="content",
        old="",
        new="Python",
        source="user",
        session_id=None,
        snapshot_before={"content": ""},
        history_path=hp,
    )
    append_profile_change(
        field="content",
        old="Python",
        new="Go",
        source="user",
        session_id=None,
        snapshot_before={"content": "Python"},
        history_path=hp,
    )
    rolled_back = rollback_profile(hp)
    assert rolled_back.content == "Python"  # 回到最后一条变更前的状态


def test_rollback_skips_corrupt_lines(tmp_path):
    """回滚跳过损坏条,用最近可解析的。"""
    hp = tmp_path / "history.jsonl"
    rec1 = json.dumps(
        {
            "ts": "x",
            "source": "user",
            "field": "content",
            "old": "",
            "new": "Python",
            "session_id": None,
            "snapshot_before": {"content": ""},
        }
    )
    rec2 = json.dumps(
        {
            "ts": "y",
            "source": "user",
            "field": "content",
            "old": "Python",
            "new": "Go",
            "session_id": None,
            "snapshot_before": {"content": "Python"},
        }
    )
    hp.write_text(
        rec1 + "\n" "CORRUPT LINE\n" + rec2 + "\n",
        encoding="utf-8",
    )
    rolled_back = rollback_profile(hp)
    assert rolled_back.content == "Python"


def test_rollback_no_history_raises(tmp_path):
    """无历史 → ValueError。"""
    hp = tmp_path / "nope.jsonl"
    with pytest.raises(ValueError, match="无可用历史版本"):
        rollback_profile(hp)


def test_rollback_all_corrupt_raises(tmp_path):
    """全坏 → ValueError。"""
    hp = tmp_path / "history.jsonl"
    hp.write_text("CORRUPT\nALSO CORRUPT\n", encoding="utf-8")
    with pytest.raises(ValueError, match="无可用历史版本"):
        rollback_profile(hp)
