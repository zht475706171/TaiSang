"""独立 LLM endpoint 连通性测试脚本。

用法:
    python scripts/test_llm.py              # 用 ~/.taisang/settings.json 的配置
    python scripts/test_llm.py --base-url X --api-key Y --model Z  # 自定义

测试项:
1. GET {base_url}/models  → 列模型(验证 endpoint 可达 + api_key 有效)
2. POST {base_url}/chat/completions  → 发一句 "ping",看响应 + 耗时
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def load_config_from_file() -> dict:
    """从 ~/.taisang/settings.json 读配置。"""
    from pathlib import Path
    p = Path.home() / ".taisang" / "settings.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def http_request(url: str, method: str = "GET", headers: dict | None = None,
                 body: dict | None = None, timeout: float = 30) -> tuple[int, str, float]:
    """发 HTTP 请求,返回 (status, body_text, elapsed_seconds)。"""
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        text = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return -1, f"URLError: {e.reason}", time.time() - t0
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}", time.time() - t0
    return status, text, time.time() - t0


def test_models_endpoint(base_url: str, api_key: str) -> None:
    """测 GET /models。"""
    print(f"\n[1] GET {base_url}/models")
    headers = {"Authorization": f"Bearer {api_key}"}
    status, text, elapsed = http_request(f"{base_url}/models", headers=headers, timeout=15)
    print(f"    status={status}  elapsed={elapsed:.2f}s")
    if status == 200:
        try:
            data = json.loads(text)
            models = [m.get("id", "?") for m in data.get("data", [])][:10]
            print(f"    OK,前 10 个模型: {models}")
        except Exception:
            print(f"    OK 但响应非标准格式: {text[:200]}")
    elif status == -1:
        print(f"    ❌ 连接失败: {text}")
    else:
        print(f"    ❌ HTTP {status}: {text[:300]}")


def test_chat_endpoint(base_url: str, api_key: str, model: str) -> None:
    """测 POST /chat/completions,发一句 ping。"""
    print(f"\n[2] POST {base_url}/chat/completions  (model={model})")
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping,回复 pong"}],
        "max_tokens": 50,
    }
    status, text, elapsed = http_request(
        f"{base_url}/chat/completions", method="POST", headers=headers, body=body, timeout=60
    )
    print(f"    status={status}  elapsed={elapsed:.2f}s")
    if status == 200:
        try:
            data = json.loads(text)
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})
            print(f"    ✅ 回复: {msg!r}")
            print(f"    usage: {usage}")
        except Exception as e:
            print(f"    ✅ 但解析失败: {e}\n    原文: {text[:300]}")
    elif status == -1:
        print(f"    ❌ 连接失败: {text}")
    else:
        print(f"    ❌ HTTP {status}: {text[:400]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM endpoint 连通性测试")
    parser.add_argument("--base-url", help="覆盖 settings.json 的 base_url")
    parser.add_argument("--api-key", help="覆盖 settings.json 的 api_key")
    parser.add_argument("--model", help="覆盖 settings.json 的 model")
    args = parser.parse_args()

    # 合并配置:CLI > settings.json
    cfg = load_config_from_file()
    llm_cfg = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}
    base_url = (args.base_url or llm_cfg.get("base_url") or "").rstrip("/")
    api_key = args.api_key or llm_cfg.get("api_key") or ""
    model = args.model or llm_cfg.get("model") or ""

    if not base_url:
        print("❌ 缺 base_url,请 --base-url 指定或先在 ~/.taisang/settings.json 配置")
        return 1
    if not api_key:
        print("❌ 缺 api_key")
        return 1
    if not model:
        print("❌ 缺 model")
        return 1

    print(f"配置:")
    print(f"  base_url: {base_url}")
    print(f"  model:    {model}")
    print(f"  api_key:  {api_key[:6]}***{api_key[-4:] if len(api_key) >= 10 else '****'}")

    test_models_endpoint(base_url, api_key)
    test_chat_endpoint(base_url, api_key, model)
    return 0


if __name__ == "__main__":
    sys.exit(main())