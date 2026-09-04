"""单个 session 的 conversation.jsonl + meta.json 读写。

线程安全:append 用 open(mode='a') 单行 write(POSIX 原子);meta.json 用
tmp + os.replace 原子替换。不同 session 不同文件,无跨 session 竞争。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class ConversationStore:
    """单个 session 的对话 transcript + 元数据读写。

    文件布局:
      <sessions_dir>/<session_id>/conversation.jsonl   # append-only 对话
      <sessions_dir>/<session_id>/meta.json            # session 元数据
    """

    def __init__(self, session_id: str, sessions_dir: Path) -> None:
        self.session_id = session_id
        self.session_dir = sessions_dir / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "conversation.jsonl"
        self.meta_path = self.session_dir / "meta.json"

    def append(self, record: dict) -> None:
        """追加一行 record 到 conversation.jsonl。

        单行 write 在 POSIX 上原子,崩溃最多丢最后一行。
        """
        # 目录可能已删(会话删除竞态/外部清理),写前自愈
        self.session_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(line)

    def load_all(self) -> list[dict]:
        """读 conversation.jsonl 全文,逐行 json.loads。

        损坏行跳过 + log warning,不抛异常。文件不存在返回 []。
        """
        if not self.jsonl_path.exists():
            return []
        records: list[dict] = []
        with open(self.jsonl_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    log.warning(
                        "conversation.jsonl 损坏行已跳过: session=%s line=%d err=%s",
                        self.session_id,
                        lineno,
                        e,
                    )
        return records

    def write_meta(self, meta: dict) -> None:
        """整体重写 meta.json。tmp 文件 + os.replace 原子替换。"""
        tmp = self.meta_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.meta_path)

    def load_meta(self) -> dict | None:
        """读 meta.json。损坏/不存在返回 None。"""
        if not self.meta_path.exists():
            return None
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("meta.json 损坏已忽略: session=%s err=%s", self.session_id, e)
            return None