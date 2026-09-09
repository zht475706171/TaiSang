from __future__ import annotations

from pathlib import Path

import pytest

from taisang.user_profile.history import (
    append_profile_change,
    read_profile_history,
    rollback_profile,
)


_EMPTY_SNAPSHOT = {
    "tech_stack": "",
    "code_style": "",
    "communication": "",
    "environment": "",
    "taboos": "",
}


def test_append_and_read_history(tmp_path):
    """追加 + 读历史。"""
    hp = tmp_path / "history.jsonl"
    append_profile_change(
        field="tech_stack",
        old="",
        new="Python",
        source="user",
        session_id=None,
        snapshot_before=_EMPTY_SNAPSHOT,
        history_path=hp,
    )
    records = read_profile_history(hp)
    assert len(records) == 1
    assert records[0]["field"] == "tech_stack"
    assert records[0]["new"] == "Python"
    assert records[0]["source"] == "user"


def test_history_keeps_latest_5(tmp_path):
    """超过 5 条,删最老的(滚动窗口)。"""
    hp = tmp_path / "history.jsonl"
    for i in range(7):
        append_profile_change(
            field="tech_stack",
            old=str(i),
            new=str(i + 1),
            source="user",
            session_id=None,
            snapshot_before={**_EMPTY_SNAPSHOT, "tech_stack": str(i)},
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
        field="tech_stack",
        old="Python",
        new="Go",
        source="agent",
        session_id="abc123",
        snapshot_before={**_EMPTY_SNAPSHOT, "tech_stack": "Python", "code_style": "4 空格"},
        history_path=hp,
    )
    records = read_profile_history(hp)
    assert records[0]["snapshot_before"]["tech_stack"] == "Python"
    assert records[0]["snapshot_before"]["code_style"] == "4 空格"
    assert records[0]["session_id"] == "abc123"


def test_history_missing_file_returns_empty(tmp_path):
    """历史文件不存在 → 空列表。"""
    hp = tmp_path / "nope.jsonl"
    assert read_profile_history(hp) == []


def test_history_corrupt_line_skipped(tmp_path):
    """损坏行跳过,不阻塞读。"""
    hp = tmp_path / "history.jsonl"
    hp.write_text(
        '{"ts":"x","source":"user","field":"tech_stack","old":"","new":"Python","session_id":null,"snapshot_before":'
        + str(_EMPTY_SNAPSHOT).replace("'", '"')
        + '}\n'
        "THIS IS NOT JSON\n"
        '{"ts":"y","source":"user","field":"code_style","old":"","new":"4 空格","session_id":null,"snapshot_before":'
        + str({**_EMPTY_SNAPSHOT, "tech_stack": "Python"}).replace("'", '"')
        + '}\n',
        encoding="utf-8",
    )
    records = read_profile_history(hp)
    assert len(records) == 2  # 损坏行跳过


def test_rollback_uses_last_snapshot_before(tmp_path):
    """回滚用最后一条 snapshot_before。"""
    hp = tmp_path / "history.jsonl"
    append_profile_change(
        field="tech_stack", old="", new="Python", source="user", session_id=None,
        snapshot_before=_EMPTY_SNAPSHOT, history_path=hp,
    )
    append_profile_change(
        field="tech_stack", old="Python", new="Go", source="user", session_id=None,
        snapshot_before={**_EMPTY_SNAPSHOT, "tech_stack": "Python"}, history_path=hp,
    )
    rolled_back = rollback_profile(hp)
    assert rolled_back.tech_stack == "Python"  # 回到最后一条变更前的状态


def test_rollback_skips_corrupt_lines(tmp_path):
    """回滚跳过损坏条,用最近可解析的。"""
    hp = tmp_path / "history.jsonl"
    hp.write_text(
        '{"ts":"x","source":"user","field":"tech_stack","old":"","new":"Python","session_id":null,"snapshot_before":'
        + str(_EMPTY_SNAPSHOT).replace("'", '"')
        + '}\n'
        "CORRUPT LINE\n"
        '{"ts":"y","source":"user","field":"code_style","old":"","new":"4 空格","session_id":null,"snapshot_before":'
        + str({**_EMPTY_SNAPSHOT, "tech_stack": "Python"}).replace("'", '"')
        + '}\n',
        encoding="utf-8",
    )
    rolled_back = rollback_profile(hp)
    assert rolled_back.tech_stack == "Python"
    assert rolled_back.code_style == ""


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