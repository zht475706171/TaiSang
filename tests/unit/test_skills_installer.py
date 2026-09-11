import pytest

from taisang.skills.installer import parse_github_source, PluginInstallError


@pytest.mark.parametrize("raw,expected", [
    ("obra/superpowers", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers.git", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers/", "github:obra/superpowers"),
    ("  obra/superpowers  ", "github:obra/superpowers"),
])
def test_parse_github_source_valid(raw, expected):
    assert parse_github_source(raw) == expected


@pytest.mark.parametrize("bad", [
    "",
    "not-a-url",
    "https://gitlab.com/obra/superpowers",  # 非 github
    "https://github.com/onlyowner",  # 缺 repo
    "https://github.com//superpowers",  # 空 owner
    "ftp://github.com/obra/superpowers",  # 非 http(s)
    # 安全边界:以下三个测试真实威胁路径
    "https://evil.com@github.com/owner/repo",  # userinfo 伪装,netloc=evil.com@github.com 被 !=
    "https://github.com:8080/owner/repo",  # 端口绕过,netloc=github.com:8080 被 !=
    "https://github.com/owner/repo;rm -rf /",  # 分号注入,regex 拒绝
])
def test_parse_github_source_invalid(bad):
    with pytest.raises(PluginInstallError):
        parse_github_source(bad)
