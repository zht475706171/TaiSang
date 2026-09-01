"""Task 2:EditTool / WriteTool 测试。"""

from taisang.agent_core.confirm import AutoApproveConfirmer, AutoDenyConfirmer
from taisang.agent_core.permission import AutoApprovePermissionManager, AutoDenyPermissionManager
from taisang.agent_core.tools import EditTool, WriteTool

# -------------------- EditTool --------------------


def test_edit_tool(tmp_path):
    """正常改文件:old 唯一 → 替换成功,返回 ok。"""
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "a.py", "old_string": "pass", "new_string": "return 1"})
    assert result["ok"] is True
    assert "return 1" in f.read_text(encoding="utf-8")
    assert "pass" not in f.read_text(encoding="utf-8")


def test_edit_path_traversal(tmp_path):
    """../../etc/passwd 应被权限器拒,返回 permission denied。"""
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoDenyPermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "../../etc/passwd", "old_string": "x", "new_string": "y"})
    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_edit_user_denies(tmp_path):
    """AutoDenyConfirmer → 改动不应用,返回 user denied,文件不变。"""
    f = tmp_path / "a.py"
    original = "def foo():\n    pass\n"
    f.write_text(original, encoding="utf-8")
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoDenyConfirmer(),
    )
    result = tool.run({"file_path": "a.py", "old_string": "pass", "new_string": "return 1"})
    assert result["ok"] is False
    assert "user denied" in result["error"]
    # 文件没动
    assert f.read_text(encoding="utf-8") == original


def test_edit_old_not_unique(tmp_path):
    """old_string 出现 2 次 → 报错 not unique,文件不变。"""
    f = tmp_path / "a.py"
    original = "x = 1\nx = 1\n"
    f.write_text(original, encoding="utf-8")
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})
    assert result["ok"] is False
    assert "not unique" in result["error"]
    assert f.read_text(encoding="utf-8") == original


def test_edit_old_not_found(tmp_path):
    """old_string 不在文件里 → 报错 not found,文件不变。"""
    f = tmp_path / "a.py"
    original = "def foo():\n    pass\n"
    f.write_text(original, encoding="utf-8")
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "a.py", "old_string": "nope_nope", "new_string": "return 1"})
    assert result["ok"] is False
    assert "not found" in result["error"]
    assert f.read_text(encoding="utf-8") == original


def test_edit_file_not_found(tmp_path):
    """文件不存在 → 报错 file not found(不是 permission denied,是文件不存在)。"""
    tool = EditTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "nope.py", "old_string": "x", "new_string": "y"})
    assert result["ok"] is False
    assert "file not found" in result["error"]


# -------------------- WriteTool --------------------


def test_write_tool(tmp_path):
    """正常创建新文件:mkdir + write,返回 ok + bytes。"""
    tool = WriteTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "new.py", "content": "print('hi')\n"})
    assert result["ok"] is True
    assert result["bytes"] == len("print('hi')\n")
    f = tmp_path / "new.py"
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "print('hi')\n"


def test_write_user_denies(tmp_path):
    """AutoDenyConfirmer → 文件不被创建,返回 user denied。"""
    tool = WriteTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoDenyConfirmer(),
    )
    result = tool.run({"file_path": "new.py", "content": "print('hi')\n"})
    assert result["ok"] is False
    assert "user denied" in result["error"]
    assert not (tmp_path / "new.py").exists()


def test_write_path_traversal(tmp_path):
    """../../tmp/x 应被权限器拒,返回 permission denied。"""
    tool = WriteTool(
        cwd=tmp_path,
        permission=AutoDenyPermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "../../tmp/x.py", "content": "x"})
    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_write_creates_parent_dirs(tmp_path):
    """写到 a/b/c.py,parent 自动 mkdir。"""
    tool = WriteTool(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoApproveConfirmer(),
    )
    result = tool.run({"file_path": "a/b/c.py", "content": "x = 1\n"})
    assert result["ok"] is True
    f = tmp_path / "a" / "b" / "c.py"
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "x = 1\n"
