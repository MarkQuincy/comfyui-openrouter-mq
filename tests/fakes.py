"""Fake OpenRouter transport for tests (no network, no key, no money)."""

import base64
import json

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)

FAKE_MODELS = [
    {
        "id": "fake/imagex-1",
        "name": "Fake Imagex 1",
        "created": 200,
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
        "supported_parameters": {
            "aspect_ratio": {"type": "enum", "values": ["1:1", "3:4"]},
            "resolution": {"type": "enum", "values": ["1K", "2K"]},
            "quality": {"type": "enum", "values": ["low", "high"]},
            "seed": {"type": "range"},
        },
    },
    {
        "id": "fake/text-only",
        "name": "Fake text-only",
        "created": 100,
        "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        "supported_parameters": {"aspect_ratio": {"type": "enum", "values": ["1:1"]}},
    },
]


class FakeTransport:
    """Callable with the ``transport`` signature. ``script`` is a list of statuses
    (or exceptions) returned for POST /images before it succeeds."""

    def __init__(self, models=None, script=(), key=None):
        self.models = FAKE_MODELS if models is None else models
        self.script = list(script)
        self.key = key or {"limit_remaining": 9.5}
        self.calls = []  # (method, url, headers, payload)

    def __call__(self, method, url, headers, body, timeout):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, headers, payload))
        if url.endswith("/images/models"):
            return 200, {"data": self.models}
        if url.endswith("/key"):
            return 200, {"data": self.key}
        if url.endswith("/credits"):
            if headers["Authorization"] != "Bearer mgmt-key":
                return 403, {"error": {"message": "management key required"}}
            return 200, {"data": {"total_credits": 50.0, "total_usage": 12.5}}
        if url.endswith("/images") and method == "POST":
            if self.script:
                step = self.script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step, {"error": {"message": "simulated"}}
            item = {"b64_json": base64.b64encode(TINY_PNG).decode()}
            return 200, {"data": [item], "usage": {"cost": 0.04}}
        return 404, {"error": {"message": "no route"}}

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]
