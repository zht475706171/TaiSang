"""~/.code-reader/ 路径管理。所有落盘位置都从这里取,便于测试用 env 覆盖。"""

from __future__ import annotations

import hashlib
from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    默认根目录是 ~/.code-reader/,测试时通过 monkeypatch HOME 隔离。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".code-reader"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        """repo clone 缓存目录。"""
        d = self.root / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _repo_hash(self, repo_url: str) -> str:
        return hashlib.sha1(repo_url.encode()).hexdigest()[:16]

    def indices_dir(self, repo_url: str) -> Path:
        """单个 repo 的索引产物目录。"""
        d = self.root / "indices" / self._repo_hash(repo_url)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def index_db_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "ast.db"

    def repo_map_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "repo_map.json"

    def chroma_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "chroma"

    def index_errors_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "index_errors.json"
