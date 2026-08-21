"""索引 SQLite 持久化。

存储三类数据:
- symbols: 按 repo_hash 存 Symbol 列表(JSON 序列化)
- fingerprints: 按 repo_hash 存 {file: hash}
- index_errors: 按 repo_hash 存失败文件清单
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..types import Symbol


class IndexStorage:
    """SQLite 索引存储。线程不安全,每 repo 一个实例。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS symbols (
                    repo_hash TEXT NOT NULL,
                    symbol_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (repo_hash, symbol_id)
                );
                CREATE TABLE IF NOT EXISTS fingerprints (
                    repo_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    PRIMARY KEY (repo_hash, file_path)
                );
                CREATE TABLE IF NOT EXISTS index_errors (
                    repo_hash TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commits (
                    repo_hash TEXT PRIMARY KEY,
                    commit_hash TEXT NOT NULL
                );
            """)

    def save_symbols(self, repo_hash: str, symbols: list[Symbol], commit_hash: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM symbols WHERE repo_hash = ?", (repo_hash,))
            c.execute(
                "INSERT OR REPLACE INTO commits(repo_hash, commit_hash) VALUES (?, ?)",
                (repo_hash, commit_hash),
            )
            for s in symbols:
                c.execute(
                    "INSERT INTO symbols(repo_hash, symbol_id, data) VALUES (?, ?, ?)",
                    (repo_hash, s.id, s.model_dump_json()),
                )

    def load_symbols(self, repo_hash: str) -> list[Symbol]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT data FROM symbols WHERE repo_hash = ?", (repo_hash,)
            ).fetchall()
        return [Symbol.model_validate_json(r[0]) for r in rows]

    def save_fingerprints(self, repo_hash: str, fingerprints: dict[str, str]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM fingerprints WHERE repo_hash = ?", (repo_hash,))
            for fp, h in fingerprints.items():
                c.execute(
                    "INSERT INTO fingerprints(repo_hash, file_path, file_hash) VALUES (?, ?, ?)",
                    (repo_hash, fp, h),
                )

    def load_fingerprints(self, repo_hash: str) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT file_path, file_hash FROM fingerprints WHERE repo_hash = ?",
                (repo_hash,),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def save_index_errors(self, repo_hash: str, errors: list[dict]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM index_errors WHERE repo_hash = ?", (repo_hash,))
            for e in errors:
                c.execute(
                    "INSERT INTO index_errors(repo_hash, data) VALUES (?, ?)",
                    (repo_hash, json.dumps(e)),
                )

    def load_index_errors(self, repo_hash: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT data FROM index_errors WHERE repo_hash = ?", (repo_hash,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]
