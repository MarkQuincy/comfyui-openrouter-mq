"""M1: OpenRouter client rules, via a fake transport and a local HTTP server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from comfy_openrouter.client import (
    NetworkError,
    NoCreditsError,
    OpenRouterClient,
    OpenRouterError,
    RateLimitError,
    ServerError,
    UnknownModelError,
    filter_params,
    max_refs,
)
from fakes import FAKE_MODELS, TINY_PNG, FakeTransport

IMAGEX, TEXT_ONLY = FAKE_MODELS


def make(transport, **kw):
    sleeps = []
    client = OpenRouterClient("test-key", transport=transport, sleep=sleeps.append, **kw)
    return client, sleeps


def test_generate_returns_image_cost_and_sent_params():
    client, _ = make(FakeTransport())
    result = client.generate(IMAGEX, "a cat", params={"aspect_ratio": "3:4", "seed": 7})
    assert result.images == [TINY_PNG]
    assert result.cost == 0.04
    assert result.params_sent == ["aspect_ratio", "seed"]
    assert result.params_dropped == []


def test_only_supported_params_are_sent():
    fake = FakeTransport()
    client, _ = make(fake)
    result = client.generate(TEXT_ONLY, "p", params={"aspect_ratio": "1:1", "quality": "high",
                                                     "resolution": "", "seed": None})
    sent = fake.posts()[0][3]
    assert sent == {"model": "fake/text-only", "prompt": "p", "aspect_ratio": "1:1"}
    assert result.params_dropped == ["quality"]


def test_filter_params_skips_empty_values():
    assert filter_params(IMAGEX, {"quality": "", "seed": 0, "n": 2}) == ({"seed": 0}, ["n"])


def test_filter_params_drops_value_not_in_enum():
    assert filter_params(IMAGEX, {"resolution": "4K", "quality": "low"}) == (
        {"quality": "low"}, ["resolution"])


def test_refs_capped_and_dropped_for_text_only():
    fake = FakeTransport()
    client, _ = make(fake)
    client.generate(IMAGEX, "p", refs=["data:a", "data:b", "data:c"])
    client.generate(TEXT_ONLY, "p", refs=["data:a"])
    first, second = fake.posts()
    assert [r["image_url"]["url"] for r in first[3]["input_references"]] == ["data:a", "data:b"]
    assert first[3]["input_references"][0]["type"] == "image_url"
    assert "input_references" not in second[3]


def test_max_refs_from_descriptor_and_default():
    model = {"architecture": {"input_modalities": ["image"]},
             "supported_parameters": {"input_references": {"max": 5}}}
    assert max_refs(model) == 5
    assert max_refs(IMAGEX) == 2
    assert max_refs(TEXT_ONLY) == 0


def test_unknown_model():
    client, _ = make(FakeTransport())
    with pytest.raises(UnknownModelError):
        client.generate(None, "p")


def test_auth_header_and_key_status():
    fake = FakeTransport(key={"limit_remaining": 42})
    client, _ = make(fake)
    assert client.key_status() == {"limit_remaining": 42}
    assert fake.calls[0][2]["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize("step", [429, 500, 503, NetworkError("down")])
def test_retryable_errors_are_retried_with_backoff(step):
    fake = FakeTransport(script=[step, step])
    client, sleeps = make(fake, backoff=1.0)
    assert client.generate(IMAGEX, "p").images
    assert len(fake.posts()) == 3  # 1 try + 2 retries
    assert sleeps == [1.0, 2.0]  # exponential


@pytest.mark.parametrize("step,error", [(429, RateLimitError), (502, ServerError),
                                        (NetworkError("down"), NetworkError)])
def test_gives_up_after_two_retries(step, error):
    fake = FakeTransport(script=[step] * 5)
    client, _ = make(fake)
    with pytest.raises(error):
        client.generate(IMAGEX, "p")
    assert len(fake.posts()) == 3


def test_402_is_not_retried_and_message_is_clear():
    fake = FakeTransport(script=[402])
    client, sleeps = make(fake)
    with pytest.raises(NoCreditsError, match="no credits"):
        client.generate(IMAGEX, "p")
    assert len(fake.posts()) == 1 and sleeps == []


def test_other_4xx_not_retried():
    fake = FakeTransport(script=[400])
    client, _ = make(fake)
    with pytest.raises(OpenRouterError) as info:
        client.generate(IMAGEX, "p")
    assert info.value.status == 400
    assert len(fake.posts()) == 1


def test_requires_api_key_and_hides_it():
    with pytest.raises(ValueError):
        OpenRouterClient("")
    assert "secret-key" not in repr(OpenRouterClient("secret-key"))


# -- real urllib transport against a local server (127.0.0.1, not OpenRouter) ----


@pytest.fixture
def local_server():
    """Answers POST /images with the queued statuses, then 200."""
    state = {"queue": [], "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.headers.get("Authorization"), body))
            if state["queue"]:
                code = state["queue"].pop(0)
                self._reply(code, {"error": {"message": f"server says {code}"}})
            else:
                self._reply(200, {"data": [{"b64_json": "aGk="}], "usage": {"cost": 0.1}})

        def _reply(self, code, payload):
            raw = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
    yield state
    server.shutdown()
    server.server_close()


def test_real_transport_retries_then_succeeds(local_server):
    local_server["queue"] = [503, 429]
    client = OpenRouterClient("test-key", base_url=local_server["url"], backoff=0.0, timeout=5)
    result = client.generate(IMAGEX, "p", params={"seed": 1})
    assert result.images == [b"hi"] and result.cost == 0.1
    assert len(local_server["requests"]) == 3
    auth, body = local_server["requests"][0]
    assert auth == "Bearer test-key" and body["seed"] == 1


def test_real_transport_402_not_retried(local_server):
    local_server["queue"] = [402, 402]
    client = OpenRouterClient("test-key", base_url=local_server["url"], backoff=0.0, timeout=5)
    with pytest.raises(NoCreditsError, match="server says 402"):
        client.generate(IMAGEX, "p")
    assert len(local_server["requests"]) == 1


def test_real_transport_network_error_is_retried():
    sleeps = []
    # Port 9 on localhost: nothing listens, connection is refused immediately.
    client = OpenRouterClient("test-key", base_url="http://127.0.0.1:9", timeout=2,
                              sleep=sleeps.append)
    with pytest.raises(NetworkError):
        client.list_models()
    assert sleeps == [1.0, 2.0]
