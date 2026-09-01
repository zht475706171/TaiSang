"""测试 SSE 编码 + EventBroker 多订阅者。"""

import queue
import threading

from taisang.web.sse import EventBroker, format_sse


def test_format_sse_basic():
    """format_sse 产出标准 SSE 三行结构(event/data/空行)。"""
    out = format_sse("tool_call", {"name": "grep", "args": {"pattern": "foo"}})
    assert out.startswith("event: tool_call\n")
    assert "data: " in out
    assert out.endswith("\n\n")
    # data 行应是合法 JSON
    data_line = [ln for ln in out.splitlines() if ln.startswith("data: ")][0]
    payload = data_line[len("data: ") :]
    import json

    assert json.loads(payload)["name"] == "grep"


def test_format_sse_non_ascii_not_escaped():
    """中文 payload 不应被 escape 成 \\uXXXX(ensure_ascii=False)。"""
    out = format_sse("final_answer", {"text": "你好世界"})
    assert "你好世界" in out


def test_eventbroker_publish_reaches_all_subscribers():
    """publish 一条事件,所有订阅队列都应收到。"""
    broker = EventBroker()
    q1 = broker.subscribe()
    q2 = broker.subscribe()
    broker.publish("llm_thinking", {})
    e1 = q1.get(timeout=1)
    e2 = q2.get(timeout=1)
    assert e1 == e2 == {"type": "llm_thinking", "payload": {}}


def test_eventbroker_unsubscribe_stops_receiving():
    """unsubscribe 后再 publish,该队列不应收到。"""
    broker = EventBroker()
    q = broker.subscribe()
    broker.unsubscribe(q)
    broker.publish("llm_thinking", {})
    with __import__("pytest").raises(queue.Empty):
        q.get(timeout=0.2)


def test_eventbroker_subscribe_unsubscribe_threadsafe():
    """并发 subscribe/unsubscribe/publish 不崩(烟雾测试)。"""
    broker = EventBroker()

    def hammer():
        for _ in range(50):
            q = broker.subscribe()
            broker.publish("llm_thinking", {})
            broker.unsubscribe(q)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    # 跑完不崩即过
    assert True
