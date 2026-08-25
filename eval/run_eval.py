"""评测脚本:跑 doc agent 产 fastapi 文档,准备给读者阅读。

用法:python eval/run_eval.py [fastapi_path]
前提:已经 git clone fastapi 到本地。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FASTAPI_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "~/repos/fastapi").expanduser()


def main() -> None:
    """跑 doc agent 为 fastapi 生成文档,提示用户找 3 个读者评测。"""
    if not FASTAPI_PATH.is_dir():
        print(f"错误:fastapi 不在 {FASTAPI_PATH},请先 git clone")
        sys.exit(1)
    print(f"跑 doc agent 为 {FASTAPI_PATH} 生成文档...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "code_reader",
            "doc",
            str(FASTAPI_PATH),
        ],
        check=True,
    )
    doc_dir = FASTAPI_PATH / ".code-reader" / "docs"
    print(f"文档产物:{doc_dir}")
    print("请找 3 个没读过 fastapi 的开发者按 eval/rubric.md 评测")


if __name__ == "__main__":
    main()
