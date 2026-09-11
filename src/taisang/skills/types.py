from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str
    allowed_tools: list[str] | None
    dir_path: Path
    content: str
    source: str
    disabled: bool = False
    plugin_name: str | None = None