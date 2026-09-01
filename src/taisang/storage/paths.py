"""路径管理。本地 repo 上下文产物落 <repo>/.taisang/。

~/.taisang/ 只保留 settings.json(LLM 配置)。
本地 repo 的会话/observation 等上下文管理产物落到 <source_root>/.taisang/。
"""

from __future__ import annotations

from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    本地 repo 上下文产物落 <source_root>/.taisang/。
    ~/.taisang/ 只保留 settings.json。
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
    def session_memory_dir(cls, source_root: Path, session_id: str) -> Path:
        """session memory 目录:.taisang/sessions/<id>/session-memory/"""
        d = source_root / ".taisang" / "sessions" / session_id / "session-memory"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_path(cls, source_root: Path, session_id: str) -> Path:
        """session memory summary 路径。"""
        return cls.session_memory_dir(source_root, session_id) / "summary.md"

    @classmethod
    def observations_dir(cls, source_root: Path) -> Path:
        """大 observation 持久化目录:.taisang/observations/"""
        d = source_root / ".taisang" / "observations"
        d.mkdir(parents=True, exist_ok=True)
        return d
