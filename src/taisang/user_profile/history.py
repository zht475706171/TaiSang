"""画像变更历史:追加到 ~/.taisang/profile_history.jsonl,最近 5 条。

每条带 snapshot_before(变更前完整 5 栏快照),回滚 O(1) 读一条。
损坏行读时跳过,回滚时从最后往前找第一条可解析的。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .types import UserProfile

_DEFAULT_HISTORY_PATH = Path.home() / ".taisang" / "profile_history.jsonl"
_MAX_HISTORY = 5


def _now_iso() -> str:
    """ISO8601 带本地时区。"""
    return datetime.now(timezone.utc).astimezone().isoformat()


def _read_all_lines(history_path: Path) -> list[str]:
    """读全量行,文件不存在返回空。"""
    if not history_path.exists():
        return []
    try:
        return history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _parse_records(lines: list[str]) -> list[dict[str, Any]]:
    """逐行解析,跳过损坏行。"""
    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                records.append(rec)
        except json.JSONDecodeError:
            continue
    return records


def _write_records(history_path: Path, records: list[dict[str, Any]]) -> None:
    """原子重写历史文件(≤5 条,全文重写无性能问题)。"""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, history_path)


def append_profile_change(
    field: str,
    old: str,
    new: str,
    source: str,
    session_id: str | None,
    snapshot_before: dict[str, Any],
    history_path: Path | None = None,
) -> None:
    """追加一条变更记录,滚动保留最近 5 条。"""
    hp = history_path or _DEFAULT_HISTORY_PATH
    records = _parse_records(_read_all_lines(hp))
    records.append(
        {
            "ts": _now_iso(),
            "source": source,
            "field": field,
            "old": old,
            "new": new,
            "session_id": session_id,
            "snapshot_before": snapshot_before,
        }
    )
    # 滚动窗口:只留最后 5 条
    if len(records) > _MAX_HISTORY:
        records = records[-_MAX_HISTORY:]
    _write_records(hp, records)


def read_profile_history(history_path: Path | None = None) -> list[dict[str, Any]]:
    """读全部历史(≤5 条),损坏行跳过。按时间正序(最老在前)。"""
    hp = history_path or _DEFAULT_HISTORY_PATH
    return _parse_records(_read_all_lines(hp))


def rollback_profile(history_path: Path | None = None) -> UserProfile:
    """回滚到上一版本:从最后往前找第一条带合法 snapshot_before 的记录。

    无历史或全坏 → ValueError。
    """
    hp = history_path or _DEFAULT_HISTORY_PATH
    records = _parse_records(_read_all_lines(hp))
    for rec in reversed(records):
        snapshot = rec.get("snapshot_before")
        if not isinstance(snapshot, dict):
            continue
        try:
            return UserProfile(**snapshot)
        except (ValidationError, TypeError):
            continue
    raise ValueError("无可用历史版本")