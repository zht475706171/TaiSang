"""测试文件指纹:同一文件 hash 稳定,不同文件 hash 不同,内容变 hash 变。"""

from code_reader.indexer.fingerprint import diff_files, file_hash


def test_file_hash_stable(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2


def test_file_hash_changes_with_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    h1 = file_hash(f)
    f.write_text("print('bye')\n", encoding="utf-8")
    h2 = file_hash(f)
    assert h1 != h2


def test_diff_files_detects_added_modified_deleted(tmp_path):
    old = {"a.py": "hash-a-old", "b.py": "hash-b", "d.py": "hash-d"}
    new = {"a.py": "hash-a-new", "b.py": "hash-b", "c.py": "hash-c"}
    added, modified, deleted, unchanged = diff_files(old, new)
    assert added == {"c.py"}
    assert modified == {"a.py"}
    assert deleted == {"d.py"}
    assert unchanged == {"b.py"}
