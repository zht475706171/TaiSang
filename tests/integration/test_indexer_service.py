"""测试 indexer service 端到端:本地 repo → RepoIndex。"""

import os
import subprocess
from pathlib import Path

from code_reader.indexer.service import IndexerService
from code_reader.storage.paths import PathManager


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8"
    )
    (repo / "b.py").write_text(
        "from a import foo\n\ndef baz():\n    return foo()\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


def test_index_builds_repoindex(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(remote)
    assert idx.source_root == str(remote)
    assert len(idx.commit_hash) > 0
    # foo, bar, baz 三个函数都应被抽出来
    names = {s.name for s in idx.symbols}
    assert {"foo", "bar", "baz"}.issubset(names)
    assert "a.py" in idx.files and "b.py" in idx.files


def test_index_builds_call_graph(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(remote)
    graph = service.build_call_graph(idx)
    # a.py::foo 调 bar,应解析到 a.py::bar
    assert "a.py::bar" in graph["a.py::foo"].resolved_calls
    # b.py::baz 调 foo,应解析到 a.py::foo
    assert "a.py::foo" in graph["b.py::baz"].resolved_calls


def test_index_persists_to_storage(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    service.build(remote)
    # 第二次 build 应该走增量路径(不报错即过)
    idx2 = service.build(remote)
    assert len(idx2.symbols) > 0


def test_index_records_errors_for_bad_files(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    repo = tmp_path / "with-bad"
    repo.mkdir()
    (repo / "good.py").write_text("def ok():\n    pass\n", encoding="utf-8")
    (repo / "bad.py").write_text("def broken(\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(repo)
    # bad.py 应在 index_errors 里
    assert any(e["file"] == "bad.py" for e in idx.index_errors)
    # good.py 的符号应该在
    assert any(s.name == "ok" for s in idx.symbols)


def test_index_excludes_code_reader_dir(tmp_path, monkeypatch):
    """索引时应排除 .code-reader/ 目录,不解析里面的文件。"""
    _isolate_home(tmp_path, monkeypatch)
    repo = tmp_path / "with-cr"
    repo.mkdir()
    (repo / "real.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    cr_dir = repo / ".code-reader"
    cr_dir.mkdir()
    (cr_dir / "fake.py").write_text("def fake():\n    pass\n", encoding="utf-8")

    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(repo)
    assert "real.py" in idx.files
    assert ".code-reader/fake.py" not in idx.files
    assert all(not f.startswith(".code-reader/") for f in idx.files)


def test_update_only_re_parses_changed_files(tmp_path, monkeypatch):
    """update() 应只重解析变动文件,未改文件不重新 parse。

    用 parse_file 调用计数验证增量路径(而非仅验证结果集)。
    """
    _isolate_home(tmp_path, monkeypatch)
    repo = tmp_path / "incr"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")

    pm = PathManager()
    service = IndexerService(pm)
    idx1 = service.build(repo)
    assert {s.name for s in idx1.symbols} == {"foo", "bar"}

    # 改 a.py,不动 b.py
    (repo / "a.py").write_text(
        "def foo():\n    return 99\n\ndef new_func():\n    pass\n", encoding="utf-8"
    )

    # 包 parse_file 计数:记录被调用的文件 rel path
    import code_reader.indexer.service as service_mod

    original_parse = service_mod.parse_file
    called_files: list[str] = []

    def spy_parse_file(path, file_rel):
        called_files.append(file_rel)
        return original_parse(path, file_rel)

    monkeypatch.setattr(service_mod, "parse_file", spy_parse_file)

    idx2 = service.update(repo)

    # 增量语义:a.py 应被重新 parse,b.py 不应被 parse
    assert "a.py" in called_files
    assert "b.py" not in called_files

    # 结果集正确性
    names = {s.name for s in idx2.symbols}
    assert "new_func" in names
    assert "bar" in names
    assert "foo" in names
