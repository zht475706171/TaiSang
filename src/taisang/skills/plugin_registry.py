"""installed_plugins.json 读写:记录用户已安装的 plugin 索引。

格式:
{
  "version": 1,
  "plugins": {
    "<plugin-name>": {
      "name": "<plugin-name>",
      "source": "github:owner/repo",
      "version": "x.y.z",
      "git_commit_sha": "12-char-short-sha",
      "installed_at": "ISO-8601 UTC",
      "skills": ["skill1", "skill2", ...]
    }
  }
}

原子写(tmp + os.replace);损坏文件当空 dict 处理并 log warning。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class InstalledPlugin:
    name: str
    source: str
    version: str
    git_commit_sha: str
    installed_at: str
    skills: list[str] = field(default_factory=list)


def load_plugins(plugins_file: Path) -> dict[str, InstalledPlugin]:
    """读 installed_plugins.json,返回 {name: InstalledPlugin}。

    文件不存在或损坏 → 返回 {} 并 log warning(损坏时)。
    """
    if not plugins_file.exists():
        return {}
    try:
        raw = json.loads(plugins_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("installed_plugins.json 损坏,当作空配置: %s", e)
        return {}
    plugins_raw = raw.get("plugins", {}) if isinstance(raw, dict) else {}
    result: dict[str, InstalledPlugin] = {}
    for name, p in plugins_raw.items():
        if not isinstance(p, dict):
            continue
        try:
            result[name] = InstalledPlugin(
                name=p.get("name", name),
                source=p.get("source", ""),
                version=p.get("version", ""),
                git_commit_sha=p.get("git_commit_sha", ""),
                installed_at=p.get("installed_at", ""),
                skills=list(p.get("skills", [])),
            )
        except (TypeError, ValueError):
            continue
    return result


def save_plugins(plugins_file: Path, plugins: dict[str, InstalledPlugin]) -> None:
    """原子写 installed_plugins.json。"""
    plugins_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "plugins": {name: asdict(p) for name, p in plugins.items()},
    }
    tmp = plugins_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, plugins_file)


def upsert_plugin(plugins_file: Path, plugin: InstalledPlugin) -> None:
    """覆盖式写入单个 plugin(同名覆盖,其他保留)。"""
    plugins = load_plugins(plugins_file)
    plugins[plugin.name] = plugin
    save_plugins(plugins_file, plugins)


def remove_plugin(plugins_file: Path, name: str) -> None:
    """删除单个 plugin 条目;不存在则 no-op。"""
    plugins = load_plugins(plugins_file)
    if name in plugins:
        del plugins[name]
        save_plugins(plugins_file, plugins)