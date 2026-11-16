"""M4: balance route logic, refresh models, cost sent to the browser."""

import json
from pathlib import Path

from comfy_openrouter import balance, routes
from comfy_openrouter import generate_node as g
from comfy_openrouter.client import OpenRouterClient
from fakes import FakeTransport


def client(api_key="api-key", **kw):
    return OpenRouterClient(api_key, transport=FakeTransport(**kw), sleep=lambda s: None)


def test_balance_with_key_only(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)
    data = balance.balance_payload(client(key={"limit": 10, "limit_remaining": 7.5,
                                               "usage": 2.5, "label": "x"}))
    assert data == {"key": {"limit": 10, "limit_remaining": 7.5, "usage": 2.5},
                    "credits": None, "errors": []}


def test_balance_with_management_key():
    data = balance.balance_payload(client(), client("mgmt-key"))
    assert data["credits"] == {"total_credits": 50.0, "total_usage": 12.5, "remaining": 37.5}
    assert data["errors"] == []


def test_credits_error_is_reported_not_raised():
    data = balance.balance_payload(client(), client("wrong-key"))
    assert data["credits"] is None
    assert data["errors"] == ["credits: OpenRouter HTTP 403: management key required"]
    assert data["key"]["limit_remaining"] == 9.5


def test_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)
    data = balance.balance_payload()
    assert data == {"key": None, "credits": None, "errors": ["OPENROUTER_API_KEY is not set"]}


def test_key_error_is_reported():
    def down(method, url, headers, body, timeout):
        return 500, None

    broken = OpenRouterClient("api-key", transport=down, retries=0, sleep=lambda s: None)
    data = balance.balance_payload(broken, None)
    assert data["key"] is None and data["errors"] == ["key: OpenRouter HTTP 500"]


def test_payload_never_contains_keys():
    data = balance.balance_payload(client("api-key"), client("mgmt-key"))
    text = json.dumps(data)
    assert "api-key" not in text and "mgmt-key" not in text


def test_refresh_models_writes_all_caches(tmp_path):
    result = balance.refresh_models_payload(client(), cache_dir=tmp_path)
    assert result == {"count": 4, "error": None}  # 2 image + 1 video + 1 speech
    for name, n in [("models_cache.json", 2), ("video_models_cache.json", 1),
                    ("speech_models_cache.json", 1)]:
        assert len(json.loads((tmp_path / name).read_text(encoding="utf-8"))["data"]) == n


def test_refresh_models_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert balance.refresh_models_payload() == {"count": 0,
                                                "error": "OPENROUTER_API_KEY is not set"}


def test_routes_do_nothing_outside_comfyui():
    assert routes.register() is False


def test_ui_payload_for_browser():
    info = {"model": "a/b", "cost_usd": 0.039}
    assert g.ui_payload(info, [Path("x") / "f_001.png"]) == {
        "openrouter": [{"cost_usd": 0.039, "model": "a/b", "files": ["f_001.png"]}]}


def test_web_extension_present():
    js = (Path(__file__).resolve().parent.parent / "web" / "openrouter.js").read_text(
        encoding="utf-8")
    assert "/openrouter/balance" in js and "/openrouter/refresh_models" in js
    assert '"OpenRouterGenerate"' in js
