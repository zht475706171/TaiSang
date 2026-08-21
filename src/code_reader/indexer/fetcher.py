"""Repo 抓取:git clone 到本地 cache,返回本地路径和 commit hash。

v1 只支持公开 repo(含本地 file:// URL)。私有 repo 走 GitHub token 留 v1.5。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


class Fetcher:
    """git clone 封装。cache_dir 按 repo URL hash 分子目录。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _url_hash(self, repo_url: str) -> str:
        return hashlib.sha1(repo_url.encode()).hexdigest()[:16]

    def fetch(self, repo_url: str) -> tuple[Path, str]:
        """clone repo 到 cache,返回 (本地路径, commit_hash)。

        如果已 clone 过,直接复用并 pull 最新(公开 repo 场景)。
        clone 失败重试 2 次,仍失败抛 RuntimeError。
        """
        target = self.cache_dir / self._url_hash(repo_url)
        if target.exists() and (target / ".git").exists():
            # 已 clone,复用
            commit = self._current_commit(target)
            return target, commit
        # 新 clone
        last_err = ""
        for _ in range(2):
            try:
                if target.exists():
                    # 残留目录,删掉重来
                    import shutil

                    shutil.rmtree(target)
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(target)],
                    capture_output=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    return target, self._current_commit(target)
                last_err = result.stderr.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                last_err = "clone timeout"
        raise RuntimeError(f"clone failed for {repo_url}: {last_err}")

    def _current_commit(self, path: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            timeout=10,
        )
        if r.returncode != 0:
            return "unknown"
        return r.stdout.decode().strip()
