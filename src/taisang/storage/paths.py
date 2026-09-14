"""路径管理。session 产物统一落 ~/.taisang/sessions/。

~/.taisang/ 保留:
- settings.json(LLM 配置)
- sessions/  所有会话产物(conversation.jsonl / meta.json / session-memory / observations)

跟 repo 解耦:换 repo / 不指定 repo 都能看到全部历史会话。
启动时 migrate_legacy_sessions 把旧 <source_root>/.taisang/sessions/ 迁到新位置。
"""

from __future__ import annotations

import shutil
from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    ~/.taisang/ 保留 settings.json + sessions/。
    session 产物按 session_id 落 ~/.taisang/sessions/<id>/,跟 repo 解耦。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".taisang"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def settings_path(self) -> Path:
        """LLM 配置文件路径。"""
        return self.root / "settings.json"

    @classmethod
    def sessions_dir(cls) -> Path:
        """所有 session 的统一存储目录:~/.taisang/sessions/。

        跟 repo 解耦,换 repo / 不指定 repo 都能看到全部历史。
        必须在方法体内调 Path.home()(非类常量),否则 monkeypatch HOME 不生效。
        """
        d = Path.home() / ".taisang" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_dir(cls, session_id: str) -> Path:
        """session memory 目录:~/.taisang/sessions/<id>/session-memory/"""
        d = cls.sessions_dir() / session_id / "session-memory"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_path(cls, session_id: str) -> Path:
        """session memory summary 路径。"""
        return cls.session_memory_dir(session_id) / "summary.md"

    @classmethod
    def observations_dir(cls, session_id: str) -> Path:
        """大 observation 持久化目录:~/.taisang/sessions/<id>/observations/。

        按 session 隔离(跟 session 走),删 session 一次 rmtree 全清。
        """
        d = cls.sessions_dir() / session_id / "observations"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def migrate_legacy_sessions(cls, source_root: Path) -> int:
        """启动时迁移旧 source_root/.taisang/sessions/ 到 ~/.taisang/sessions/。

        目标已存在则跳过(不覆盖)。返回迁移数量。
        旧 observations 不迁移(全局共享无法按 session 归属)。
        """
        legacy = source_root / ".taisang" / "sessions"
        if not legacy.is_dir():
            return 0
        dest = cls.sessions_dir()
        count = 0
        for sub in legacy.iterdir():
            if not sub.is_dir():
                continue
            target = dest / sub.name
            if target.exists():
                continue  # 不覆盖
            shutil.move(str(sub), str(target))
            count += 1
        return count