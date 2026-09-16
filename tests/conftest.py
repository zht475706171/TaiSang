"""pytest 全局 fixture / 环境设置。

跑测试时关闭日志落盘,避免污染开发者家目录的 ~/.taisang/logs/taisang.log。
必须在 conftest.py 顶层(setenv 早于任何 _setup_logging 调用)。
"""

from __future__ import annotations

import os

# 设在模块顶层:pytest 加载 conftest 时立即生效,早于任何测试 import 触发
# cli.main._setup_logging。用 setdefault 避免覆盖开发者故意设的值。
os.environ.setdefault("TAISANG_NO_FILE_LOG", "1")