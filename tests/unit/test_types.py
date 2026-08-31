"""测试核心数据类型能正确构造和序列化。

清理后只保留 Citation + Answer(其余索引时代类型已删)。
"""

from code_reader.types import Answer, Citation


def test_citation_and_answer():
    c = Citation(file="app.py", line_range=(1, 10), symbol_id="app.py::main")
    a = Answer(
        text="main 是应用入口",
        citations=[c],
        complete=True,
    )
    assert a.citations[0].file == "app.py"
    assert a.complete is True


def test_answer_default_citations_empty():
    a = Answer(text="hello")
    assert a.citations == []
    assert a.complete is True
    assert a.steps_used == 0


def test_citation_optional_symbol_id():
    c = Citation(file="app.py", line_range=(5, 8))
    assert c.symbol_id is None


def test_answer_json_round_trip():
    """Answer should survive model_dump_json + model_validate_json round-trip."""
    original = Answer(
        text="main 是应用入口",
        citations=[Citation(file="app.py", line_range=(1, 10), symbol_id="app.py::main")],
        complete=False,
        steps_used=3,
    )
    json_str = original.model_dump_json()
    restored = Answer.model_validate_json(json_str)
    assert restored == original
    assert restored.citations[0].file == "app.py"
    assert restored.steps_used == 3
