"""本地 repo 探针:取 commit hash。

v1 不做远程 git clone。用户先 `git clone` 到本地,再 `code-reader index <path>`。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class Fetcher:
    """本地 repo 探针。v1 不做远程 clone,只取 commit hash。"""

    def __init__(self) -> None:
        pass  # 不再需要 cache_dir

    @staticmethod
    def current_commit(path: Path) -> str:
        """取本地 repo 的 HEAD commit hash。

        无 .git / git 未装 / git 命令失败,统一返回 'unknown',不抛异常。
        """
        try:
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=path,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("git rev-parse failed for %s: %s", path, e)
            return "unknown"
        if r.returncode != 0:
            return "unknown"
        return r.stdout.decode().strip()
