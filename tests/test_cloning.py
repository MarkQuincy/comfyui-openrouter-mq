"""Voice cloning: voice samples -> input_references, notes per model, recipe refs."""

import base64
import hashlib

import pytest

from comfy_openrouter import cloning
from comfy_openrouter import speak_node as s
from comfy_openrouter.client import OpenRouterClient, OpenRouterError
from fakes import FakeTransport

CLIP = cloning.wav_from_pcm16(b"\x00\x00\xff\x7f" * 12000, 1, 24000)  # 1 s mono
SETTINGS = {"voice": "", "format": "mp3", "speed": 1.0, "instructions": ""}
SEED = {"id": "bytedance-seed/seed-audio-1-0"}


def client_with(fake):
    return OpenRouterClient("k", transport=fake, sleep=lambda x: None)


def test_notes_per_model():
    assert cloning.note("bytedance-seed/seed-audio-1-0").startswith("Voice cloning: yes")
    assert "@Audio1" in cloning.note("bytedance-seed/seed-audio-1-0")
    assert cloning.note("fish-audio/s2.1-pro").startswith("Voice cloning: yes")
    assert cloning.note("mistralai/voxtral-tts").startswith("Voice cloning: yes")
    assert cloning.note("heygen/heygen-voice-1").startswith("Voice cloning: yes")
    assert cloning.note("elevenlabs/eleven-v4") == cloning.UNKNOWN


def test_references_shape_and_transcript_after_first_clip():
    parts, refs = cloning.references([CLIP, CLIP], "Hello there")
    assert [p["type"] for p in parts] == ["input_audio", "text", "input_audio"]
    data = parts[0]["input_audio"]["data"]
    assert data.startswith("data:audio/wav;base64,")
    assert base64.b64decode(data.split(",", 1)[1]) == CLIP
    assert parts[1] == {"type": "text", "text": "Hello there"}
    assert refs[0] == {"audio_hash": "sha256:" + hashlib.sha256(CLIP).hexdigest(),
                       "seconds": 1.0}


def test_limits():
    with pytest.raises(ValueError, match="At most 3"):
        cloning.references([CLIP] * 4)
    with pytest.raises(ValueError, match="10000"):
        cloning.references([CLIP], "x" * 10_001)
    with pytest.raises(ValueError, match="15 MB"):
        cloning.references([b"0" * (cloning.MAX_CLIP_BYTES + 1)])


def test_speak_with_sample_sends_references_not_voice():
    fake = FakeTransport()
    settings = {**SETTINGS, "voice": "nova"}
    _, info = s.speak(client_with(fake), SEED, "@Audio1 Hi", settings, [CLIP], "Sample words")
    sent = fake.posts()[0][3]
    assert "voice" not in sent
    assert sent["input_references"][0]["type"] == "input_audio"
    assert sent["input_references"][1] == {"type": "text", "text": "Sample words"}
    assert info["refs_sent"] == 1 and info["refs"][0]["seconds"] == 1.0
    assert info["params"]["sample_text"] == "Sample words"
    assert "input_references" not in info["params"]  # no audio bytes in the recipe


def test_rejected_sample_explains_cloning_support():
    class NoCloning(FakeTransport):
        def __call__(self, method, url, headers, body, timeout):
            if url.endswith("/audio/speech"):
                return 400, {"error": {"message": "input_references not supported"}}
            return super().__call__(method, url, headers, body, timeout)

    with pytest.raises(OpenRouterError, match="not listed for this model"):
        s.speak(client_with(NoCloning()), {"id": "elevenlabs/eleven-v4"}, "Hi", SETTINGS,
                [CLIP])


def test_recipe_keeps_sample_fingerprint(tmp_path):
    import json

    _, info = s.speak(client_with(FakeTransport()), SEED, "Hi", SETTINGS, [CLIP])
    path = s.save_speech(b"ID3", "mp3", info, "Hi", None, "clone", tmp_path, "{name}_{counter}")
    recipe = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert recipe["refs"] == info["refs"] and recipe["kind"] == "audio"
