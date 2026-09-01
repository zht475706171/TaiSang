# tests/unit/test_session_memory.py
"""session_memory:分支 agent 异步维护笔记测试。

覆盖:
- 模板初始化(10 章节默认模板)
- should_extract 3 道阈值门控
- read_for_compaction 空模板/已更新
- _do_extract 调分支 agent + forked_agent 安全闸(只允许 Edit memory_path)
"""

from taisang.llm_client import LLMResponse, MockLLM
from taisang.session_memory.service import (
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
    """extract 调 LLM,让 LLM 用 Edit 工具更新笔记(异步,等 worker 完成)。

    多轮 loop:第 1 轮 LLM 给 Edit tool_call,第 2 轮 LLM 停(空 tool_calls)。
    """
    import json
    import time

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")
    # mock LLM:resp1 给 Edit tool_call,resp2 空停
    mock = MockLLM(
        [
            LLMResponse(
                text="更新笔记",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(memory_path),
                                    "old_string": "(old)",
                                    "new_string": "(new content)",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            ),
            LLMResponse(text="done", tool_calls=[]),
        ]
    )
    service = SessionMemoryService(llm=mock, memory_path=memory_path)
    # 直接调 _do_extract(绕过 should_extract)— 异步启动后台线程
    service._do_extract(recent_conversation="最新对话:写了 00_项目是什么.md")
    # 等 worker 线程完成(_extracting 清零)
    deadline = time.time() + 5
    while service._extracting and time.time() < deadline:
        time.sleep(0.01)
    assert not service._extracting, "extract worker did not finish in 5s"
    # 笔记内容更新了
    assert "(new content)" in memory_path.read_text(encoding="utf-8")


def test_forked_agent_denies_non_edit_tool(tmp_path):
    """mock LLM 返回非 Edit 工具(Write)→ 被 deny,memory_path 内容不变。

    多轮:resp1 给 Write(deny),resp2 停。
    """
    import json

    from taisang.session_memory.forked_agent import run_forked_agent

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
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "Write",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(memory_path),
                                    "content": "HACKED",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            ),
            LLMResponse(text="done", tool_calls=[]),
        ]
    )
    run_forked_agent(mock, memory_path, "test prompt")
    # 内容不变
    assert memory_path.read_text(encoding="utf-8") == original


def test_forked_agent_denies_edit_wrong_file(tmp_path):
    """mock LLM 返回 Edit 但 file_path 指向别的文件 → deny,memory_path 不变。"""
    import json

    from taisang.session_memory.forked_agent import run_forked_agent

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
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(other_path),
                                    "old_string": "OTHER",
                                    "new_string": "HACKED",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            ),
            LLMResponse(text="done", tool_calls=[]),
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


# -------------------- 异步 + 错误处理 --------------------


def test_extract_is_async_non_blocking(tmp_path):
    """_do_extract 启动后台线程,立即返回,不阻塞主流程。

    用一个 sleep 2s 的 mock LLM 证明:调 _do_extract 后 0.1s 内拿到控制权。
    """
    import time

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")

    class SlowLLM:
        def chat(self, messages, tools):
            time.sleep(2)  # 模拟慢 LLM
            return LLMResponse(text="", tool_calls=[])

    service = SessionMemoryService(llm=SlowLLM(), memory_path=memory_path)
    t0 = time.time()
    service._do_extract(recent_conversation="test")
    elapsed = time.time() - t0
    # 异步:0.1s 内返回(不是 2s)
    assert elapsed < 0.1, f"_do_extract blocked for {elapsed:.2f}s, expected async"
    # _extracting 标志已置
    assert service._extracting is True


def test_extract_failure_does_not_propagate(tmp_path):
    """extract worker 抛异常(超时/网络错)不传播到主流程,只 log warning。"""
    import time

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")

    class FailingLLM:
        def chat(self, messages, tools):
            raise RuntimeError("simulated LLM timeout")

    service = SessionMemoryService(llm=FailingLLM(), memory_path=memory_path)
    # 调 _do_extract 不抛异常(后台 worker 会失败,但主流程不知)
    service._do_extract(recent_conversation="test")
    # 等 worker 完成
    deadline = time.time() + 5
    while service._extracting and time.time() < deadline:
        time.sleep(0.01)
    assert not service._extracting, "worker did not finish"
    # 笔记文件没被改(LLM 失败了)
    assert "(old)" in memory_path.read_text(encoding="utf-8")


def test_extract_skipped_when_already_running(tmp_path):
    """已在提取中(_extracting=True)时,should_extract 返回 False,不重复触发。"""
    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")

    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    # 模拟上一次还在跑
    service._extracting = True
    # should_extract 应返回 False(已在跑)
    assert service.should_extract(current_tokens=20_000, tool_calls_since_last=10) is False
    # _do_extract 也应跳过(不启动新线程)
    service._do_extract(recent_conversation="test")  # 应立即返回不启动 worker
    # _extracting 仍 True(没被覆盖)
    assert service._extracting is True


# -------------------- 多轮 loop + idle_break + 不截断 --------------------


def test_forked_agent_multi_turn_loop(tmp_path):
    """多轮 loop:第 1 轮 Edit一处,第 2 轮 Edit 另一处,第 3 轮停。证明 loop 能跑多轮。"""
    import json

    from taisang.session_memory.forked_agent import run_forked_agent

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old1) (old2)\n", encoding="utf-8")
    mock = MockLLM(
        [
            # 第 1 轮:Edit old1 → new1
            LLMResponse(
                text="第 1 轮",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(memory_path),
                                    "old_string": "(old1)",
                                    "new_string": "(new1)",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            ),
            # 第 2 轮:Edit old2 → new2
            LLMResponse(
                text="第 2 轮",
                tool_calls=[
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(memory_path),
                                    "old_string": "(old2)",
                                    "new_string": "(new2)",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            ),
            # 第 3 轮:停
            LLMResponse(text="done", tool_calls=[]),
        ]
    )
    run_forked_agent(mock, memory_path, "test prompt")
    content = memory_path.read_text(encoding="utf-8")
    assert "(new1)" in content
    assert "(new2)" in content


def test_forked_agent_max_turns_cap(tmp_path):
    """LLM 一直返回 tool_call 不停 → 达 max_turns 强制终止(不无限循环)。"""
    import json

    from taisang.session_memory.forked_agent import run_forked_agent

    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    # 笔记里永远找得到 old_string(可重复替换)
    memory_path.write_text("# Session Title\n*desc*\nX\n", encoding="utf-8")
    # 造 12 个带 Edit tool_call 的 response(max_turns=10,第 11、12 个不该被调)
    responses = []
    for i in range(12):
        responses.append(
            LLMResponse(
                text=f"轮 {i}",
                tool_calls=[
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps(
                                {
                                    "file_path": str(memory_path),
                                    "old_string": "X",
                                    "new_string": "X",  # 替换前后一样,内容不变
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            )
        )
    mock = MockLLM(responses)
    # max_turns=3 缩小测试规模(够证明 cap 生效,不用等 10 轮)
    run_forked_agent(mock, memory_path, "test prompt", max_turns=3)
    # 只应消耗 3 个 response(第 4 个没被调)
    assert len(mock.calls) == 3, f"expected 3 LLM calls (max_turns=3), got {len(mock.calls)}"


def test_should_extract_idle_break_branch(tmp_path):
    """笔记存在 + delta tokens 够 + last_turn 无 tool_call → 触发 idle_break。

    即使 tool_calls 不够也触发(自然对话断点分支)。
    """
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    service._last_extracted_tokens = 0
    # tool_calls=0(不够 3),但 last_turn_has_tool_calls=False
    assert (
        service.should_extract(
            current_tokens=6_000,
            tool_calls_since_last=0,
            last_turn_has_tool_calls=False,
        )
        is True
    )
    # 对比:同条件但 last_turn_has_tool_calls=True → 不触发(因为 tool_calls 不够)
    assert (
        service.should_extract(
            current_tokens=6_000,
            tool_calls_since_last=0,
            last_turn_has_tool_calls=True,
        )
        is False
    )


def test_should_extract_idle_break_needs_token_threshold(tmp_path):
    """idle_break 分支也要满足 delta tokens >= 5000,delta 不够不触发。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    service._last_extracted_tokens = 3_000
    # delta=1000 < 5000,即使 last_turn 无 tool_call 也不触发
    assert (
        service.should_extract(
            current_tokens=4_000,
            tool_calls_since_last=0,
            last_turn_has_tool_calls=False,
        )
        is False
    )


def test_recent_text_does_not_truncate(tmp_path):
    """_recent_text 不截断:长内容(>200 字)完整保留。"""
    from taisang.agent_core.confirm import AutoApproveConfirmer
    from taisang.agent_core.service import AgentService

    mock = MockLLM([])
    service = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
    )
    # 造一条 500 字的 user 消息
    long_content = "A" * 500
    service.ctx.append_user(long_content)
    text = service._recent_text()
    # 500 字完整保留(不是截到 200)
    assert long_content in text
    assert len(long_content) == 500
