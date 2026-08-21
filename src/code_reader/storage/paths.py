"""路径管理。本地 repo 索引产物落 <repo>/.code-reader/。

~/.code-reader/ 只保留 settings.json(LLM 配置)。
本地 repo 的索引产物(ast.db / repo_map.json 等)落到 <source_root>/.code-reader/。
"""

from __future__ import annotations

from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    本地 repo 索引产物落 <source_root>/.code-reader/。
    ~/.code-reader/ 只保留 settings.json。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".code-reader"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def settings_path(self) -> Path:
        """LLM 配置文件路径。"""
        return self.root / "settings.json"

    @staticmethod
    def index_dir(source_root: Path) -> Path:
        """单个 repo 的索引产物目录:<source_root>/.code-reader/"""
        d = source_root / ".code-reader"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def index_db_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "ast.db"

    @classmethod
    def repo_map_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "repo_map.json"

    @classmethod
    def chroma_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "chroma"

    @classmethod
    def index_errors_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "index_errors.json"
