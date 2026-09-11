"""Plugin 安装核心:git clone + 结构识别 + 批量导入 skills 到 user 源。

source 规范化:
- "owner/repo"           → "github:owner/repo"
- "https://github.com/owner/repo[.git|/]" → "github:owner/repo"

安全:
- parse_github_source 只接受 github.com + owner/repo 格式,杜绝命令注入
- git clone 用 subprocess.run 列表参数(不经 shell)
- 临时目录用 tempfile.TemporaryDirectory 自动清理
- 不执行 plugin 内任何脚本(hooks/agents/scripts 只复制不执行)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class PluginInstallError(ValueError):
    """plugin 安装失败。message 面向用户,可直接展示。"""


# owner/repo:owner 和 repo 都只能是 [A-Za-z0-9._-]+,字母数字开头
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_github_source(source: str) -> str:
    """把用户输入规范化成 'github:owner/repo'。

    接受:
      owner/repo
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      https://github.com/owner/repo/

    其他一律抛 PluginInstallError(非 github 域名、缺 owner/repo、协议错误)。
    """
    s = source.strip()
    if not s:
        raise PluginInstallError("github 地址不能为空")

    if s.startswith(("http://", "https://")):
        # 必须是 https://github.com/owner/repo 形式
        from urllib.parse import urlparse
        parsed = urlparse(s)
        if parsed.netloc != "github.com":
            raise PluginInstallError(f"只支持 github.com 仓库,收到: {parsed.netloc}")
        path = parsed.path.strip("/")
        # 去掉 .git 后缀和末尾斜杠
        if path.endswith(".git"):
            path = path[:-4].rstrip("/")
        if not _OWNER_REPO_RE.match(path):
            raise PluginInstallError(f"github 路径格式错误,期望 owner/repo: {path}")
        return f"github:{path}"

    # 简写 owner/repo
    if not _OWNER_REPO_RE.match(s):
        raise PluginInstallError(
            f"地址格式错误,期望 owner/repo 或 https://github.com/owner/repo: {s}"
        )
    return f"github:{s}"