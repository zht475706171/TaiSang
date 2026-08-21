"""文件指纹:用 sha1 计算文件内容 hash,做增量索引基础。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path) -> str:
    """计算文件内容 sha1,返回前 16 位(够用,省空间)。"""
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def diff_files(
    old: dict[str, str], new: dict[str, str]
) -> tuple[set[str], set[str], set[str], set[str]]:
    """对比新旧文件指纹字典。

    Returns: (added, modified, deleted, unchanged) 四个文件路径集合。
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    deleted = old_keys - new_keys
    common = old_keys & new_keys
    modified = {k for k in common if old[k] != new[k]}
    unchanged = {k for k in common if old[k] == new[k]}
    return added, modified, deleted, unchanged
