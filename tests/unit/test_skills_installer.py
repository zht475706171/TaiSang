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
    "",  # 空
    "not-a-url",  # 非 url 且非 owner/repo
    "https://gitlab.com/obra/superpowers",  # 非 github
    "https://github.com/onlyowner",  # 缺 repo
    "https://github.com//superpowers",  # 空 owner
    "ftp://github.com/obra/superpowers",  # 非 http(s)
    "javascript:alert(1)",  # 注入尝试
])
def test_parse_github_source_invalid(bad):
    with pytest.raises(PluginInstallError):
        parse_github_source(bad)