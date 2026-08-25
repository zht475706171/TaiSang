# tests/unit/test_session_memory.py
"""session_memory:分支 agent 异步维护笔记测试。

覆盖:
- 模板初始化(10 章节默认模板)
- should_extract 3 道阈值门控
- read_for_compaction 空模板/已更新
- _do_extract 调分支 agent + forked_agent 安全闸(只允许 Edit memory_path)
"""

from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.session_memory.service import (
    MIN_TOKENS_BETWEEN_UPDATE,
    MIN_TOKENS_TO_INIT,
    TOOL_CALLS_BETWEEN_UPDATES,
    SessionMemoryService,
)


def test_session_memory_initializes_template(tmp_path):
    """首次调用 ensure_file 时,写默认模板(10 章节)。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    assert memory_path.exists()
    content = memory_path.read_text(encoding="utf-8")
    assert "Session Title" in content
    assert "Worklog" in content
    assert content.count("# ") == 10  # 10 个章节


def test_should_extract_first_time_under_threshold(tmp_path):
    """笔记不存在 + 累积 tokens < 10000 → 不提取。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    # current_tokens=5000 < MIN_TOKENS_TO_INIT(10000)
    assert service.should_extract(current_tokens=5_000, tool_calls_since_last=0) is False


def test_should_extract_first_time_over_threshold(tmp_path):
    """笔记不存在 + 累积 tokens >= 10000 → 提取(初始化)。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    assert service.should_extract(current_tokens=15_000, tool_calls_since_last=0) is True


def test_should_extract_after_init_needs_both_gates(tmp_path):
    """笔记已存在:需要 tokens delta >= 5000 且 tool_calls >= 3,缺一不可。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    service._last_extracted_tokens = 0
    # delta 6000 >= 5000 但 tool_calls=1 < 3 → False
    assert service.should_extract(current_tokens=6_000, tool_calls_since_last=1) is False
    # tool_calls=3 >= 3 且 delta 6000 >= 5000 → True
    assert service.should_extract(current_tokens=6_000, tool_calls_since_last=3) is True
    # 临界:delta=5000 正好等于阈值 → True
    assert service.should_extract(current_tokens=5_000, tool_calls_since_last=3) is True
    # 临界:tool_calls=3 正好等于阈值,delta=5000 → True
    assert (
        service.should_extract(
            current_tokens=5_000, tool_calls_since_last=TOOL_CALLS_BETWEEN_UPDATES
        )
        is True
    )


def test_should_extract_after_init_insufficient_delta(tmp_path):
    """笔记已存在 + tool_calls 够但 delta tokens 不够 → False。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    service._last_extracted_tokens = 4_000
    # delta=1000 < 5000,tool_calls=5 够 → False
    assert service.should_extract(current_tokens=5_000, tool_calls_since_last=5) is False


def test_read_for_compaction_returns_none_for_empty_template(tmp_path):
    """笔记存在但全是 (待填) → 还是空模板,返回 None。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    # 默认模板有 8 个 (待填) 字段(还有一个 demo repo 是实际内容)
    assert service.read_for_compaction() is None


def test_read_for_compaction_returns_none_for_missing_file(tmp_path):
    """笔记文件不存在 → None。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    assert service.read_for_compaction() is None


def test_read_for_compaction_returns_content_after_update(tmp_path):
    """笔记已更新,实际内容多于阈值 → 返回笔记内容。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    # 写一个实际内容笔记(0 个 (待填))
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        "# Session Title\n*desc*\n实际内容\n# Current State\n*desc*\n已完成 3 章\n",
        encoding="utf-8",
    )
    content = service.read_for_compaction()
    assert content is not None
    assert "实际内容" in content
    assert "已完成 3 章" in content


def test_session_memory_extract_uses_forked_agent(tmp_path):
    """extract 调 LLM,让 LLM 用 Edit 工具更新笔记。"""
    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")
    # mock LLM 返回一个 tool_call:Edit summary.md
    mock = MockLLM(
        [
            LLMResponse(
                text="更新笔记",
                tool_calls=[
                    {
                        "name": "Edit",
                        "args": {
                            "file_path": str(memory_path),
                            "old_string": "(old)",
                            "new_string": "(new content)",
                        },
                    }
                ],
            )
        ]
    )
    service = SessionMemoryService(llm=mock, memory_path=memory_path)
    # 直接调 _do_extract(绕过 should_extract)
    service._do_extract(recent_conversation="最新对话:写了 00_项目是什么.md")
    # 笔记内容更新了
    assert "(new content)" in memory_path.read_text(encoding="utf-8")


def test_forked_agent_denies_non_edit_tool(tmp_path):
    """mock LLM 返回非 Edit 工具(Write)→ 被 deny,memory_path 内容不变。"""
    from code_reader.session_memory.forked_agent import run_forked_agent

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    original = "# Session Title\n*desc*\n(untouched)\n"
    memory_path.write_text(original, encoding="utf-8")
    mock = MockLLM(
        [
            LLMResponse(
                text="尝试用 Write",
                tool_calls=[
                    {
                        "name": "Write",
                        "args": {
                            "file_path": str(memory_path),
                            "content": "HACKED",
                        },
                    }
                ],
            )
        ]
    )
    run_forked_agent(mock, memory_path, "test prompt")
    # 内容不变
    assert memory_path.read_text(encoding="utf-8") == original


def test_forked_agent_denies_edit_wrong_file(tmp_path):
    """mock LLM 返回 Edit 但 file_path 指向别的文件 → deny,memory_path 不变。"""
    from code_reader.session_memory.forked_agent import run_forked_agent

    memory_path = tmp_path / "summary.md"
    other_path = tmp_path / "other.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    original = "# Session Title\n*desc*\n(keep)\n"
    memory_path.write_text(original, encoding="utf-8")
    other_path.write_text("OTHER FILE\n", encoding="utf-8")
    mock = MockLLM(
        [
            LLMResponse(
                text="尝试编辑别的文件",
                tool_calls=[
                    {
                        "name": "Edit",
                        "args": {
                            "file_path": str(other_path),
                            "old_string": "OTHER",
                            "new_string": "HACKED",
                        },
                    }
                ],
            )
        ]
    )
    run_forked_agent(mock, memory_path, "test prompt")
    # memory_path 不变
    assert memory_path.read_text(encoding="utf-8") == original
    # other_path 也未被改(_apply_edit 只对 memory_path 执行)
    assert other_path.read_text(encoding="utf-8") == "OTHER FILE\n"


def test_constants_match_plan():
    """3 道阈值门控常量按 plan 固定。"""
    assert MIN_TOKENS_TO_INIT == 10_000
    assert MIN_TOKENS_BETWEEN_UPDATE == 5_000
    assert TOOL_CALLS_BETWEEN_UPDATES == 3
