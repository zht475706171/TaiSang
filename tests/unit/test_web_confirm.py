"""测试 WebConfirmer:超时 deny、resolve 后 approve、resolve 后 deny、无效 token。"""

import threading
import time

from taisang.agent_core.events import CONFIRM_REQUEST
from taisang.web.confirm import WebConfirmer


def test_web_confirmer_timeout_returns_false():
    """无前端回应,超时后返回 False(deny)。"""
    events = []
    conf = WebConfirmer(emit=lambda t, p: events.append((t, p)), timeout=0.2)
    result = conf("a.py", "old", "new")
    assert result is False
    # 应 emit 了一个 CONFIRM_REQUEST 事件
    assert len(events) == 1
    assert events[0][0] == CONFIRM_REQUEST
    assert events[0][1]["file_path"] == "a.py"


def test_web_confirmer_resolve_approve_returns_true():
    """前端 POST approve=True,confirmer 返回 True。"""
    captured = {}
    conf = WebConfirmer(emit=lambda t, p: captured.__setitem__("token", p["token"]), timeout=2.0)

    result_box: list[bool] = []

    def call_it():
        result_box.append(conf("a.py", "old", "new"))

    th = threading.Thread(target=call_it)
    th.start()
    # 等 emit 把 token 填进去
    deadline = time.time() + 1.0
    while "token" not in captured and time.time() < deadline:
        time.sleep(0.01)
    assert "token" in captured, "CONFIRM_REQUEST 未 emit"
    ok = conf.resolve(captured["token"], approve=True)
    th.join(timeout=2.0)
    assert ok is True
    assert result_box == [True]


def test_web_confirmer_resolve_deny_returns_false():
    """前端 POST approve=False,confirmer 返回 False。"""
    captured = {}
    conf = WebConfirmer(emit=lambda t, p: captured.__setitem__("token", p["token"]), timeout=2.0)

    result_box: list[bool] = []

    def call_it():
        result_box.append(conf("a.py", "old", "new"))

    th = threading.Thread(target=call_it)
    th.start()
    deadline = time.time() + 1.0
    while "token" not in captured and time.time() < deadline:
        time.sleep(0.01)
    conf.resolve(captured["token"], approve=False)
    th.join(timeout=2.0)
    assert result_box == [False]


def test_web_confirmer_resolve_unknown_token_returns_false():
    """resolve 一个不存在的 token 返回 False(已超时或从未发起)。"""
    conf = WebConfirmer(emit=lambda t, p: None, timeout=0.1)
    assert conf.resolve("nonexistent", approve=True) is False
