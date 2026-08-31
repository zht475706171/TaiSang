"""端到端:本地多文件 repo → IndexerService 建索引 → 调用图验证。

Task 1 之后:CLI 的 index/doc 命令已删除,这里直接用 IndexerService 验证
调用图 + trace_call_chain 工具能正确解析跨文件调用链。
"""

import os
import subprocess
from pathlib import Path


def _isolate_home(tmp_path, monkeypatch):
    """Windows: Path.home() 读 USERPROFILE;Linux/Mac 读 HOME。同时 patch。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _make_realistic_repo(tmp_path: Path) -> Path:
    """造一个含跨文件调用的 repo。"""
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from utils import helper\n\n"
        "def main():\n"
        "    helper()\n"
        "    print('done')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (repo / "utils.py").write_text(
        "def helper():\n" "    return do_thing()\n\n" "def do_thing():\n" "    return 42\n",
        encoding="utf-8",
    )
    # Windows: subprocess 需要 PATH 找到 git;merge GIT_* 和当前 PATH
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=git_env,
    )
    return repo


def test_end_to_end_call_graph_built(tmp_path, monkeypatch):
    """IndexerService 建索引后调用图应能解析 main → helper → do_thing。"""
    _isolate_home(tmp_path, monkeypatch)
    repo = _make_realistic_repo(tmp_path)

    from code_reader.indexer.service import IndexerService
    from code_reader.storage.paths import PathManager

    pm = PathManager()
    service = IndexerService(pm)
    idx = service.update(repo)
    graph = service.build_call_graph(idx)
    # main 调 helper,应解析到 utils.py::helper
    assert "utils.py::helper" in graph["main.py::main"].resolved_calls
    # helper 调 do_thing,应解析到 utils.py::do_thing
    assert "utils.py::do_thing" in graph["utils.py::helper"].resolved_calls


def test_end_to_end_trace_call_chain_three_hops(tmp_path, monkeypatch):
    """trace_call_chain 工具能追 main → helper → do_thing。"""
    _isolate_home(tmp_path, monkeypatch)
    repo = _make_realistic_repo(tmp_path)

    from code_reader.agent_core.tools import TraceCallChainTool
    from code_reader.indexer.service import IndexerService
    from code_reader.storage.paths import PathManager

    pm = PathManager()
    service = IndexerService(pm)
    idx = service.update(repo)
    graph = service.build_call_graph(idx)

    tool = TraceCallChainTool(call_graph=graph)
    result = tool.run({"symbol_id": "main.py::main", "depth": 3})
    assert result["chain"] == ["main.py::main", "utils.py::helper", "utils.py::do_thing"]
