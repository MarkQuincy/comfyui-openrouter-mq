"""M6: JSON recipes for every file, Speak node, Video node (fake transport, no money)."""

import hashlib
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import pngread
from comfy_openrouter import generate_node as g
from comfy_openrouter import models as model_list
from comfy_openrouter import speak_node as s
from comfy_openrouter import video_node as v
from comfy_openrouter.client import OpenRouterClient, OpenRouterError
from comfy_openrouter.images import pixel_hash
from fakes import (FAKE_MODELS, FAKE_MP3, FAKE_MP4, FAKE_SPEECH_MODELS, FAKE_VIDEO_MODELS,
                   FakeTransport)

PATTERN = "{person}_{name}_{model}_{counter}"
CONTEXT = {"project": "P", "person": "Ivan Petrov"}
FRAME = (2, 1, "RGB", bytes([255, 0, 0, 0, 0, 255]))
VIDEO = FAKE_VIDEO_MODELS[0]
SPEECH = FAKE_SPEECH_MODELS[0]


def client_with(fake, sleeps=None):
    return OpenRouterClient("k", transport=fake,
                            sleep=(sleeps.append if sleeps is not None else lambda x: None))


def recipe(path):
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


# -- JSON recipe next to images -----------------------------------------------------


def test_png_gets_json_recipe(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_USER", "alice")
    settings = {"aspect_ratio": "3:4", "resolution": "auto", "quality": "auto", "seed": 7}
    _, info, _ = g.generate(client_with(FakeTransport()), FAKE_MODELS[0], "p", settings, [FRAME])
    (path,) = g.save_outputs([(3, 2, "RGB", bytes(18))], info, "p", CONTEXT, "face",
                             tmp_path, PATTERN)
    data = path.read_bytes()
    png_meta = json.loads(pngread.text(data)["openrouter"])
    rec = recipe(path)
    assert png_meta["schema"] == "openrouter-meta/1"  # PNG chunk unchanged
    assert rec["schema"] == "openrouter-meta/2" and rec["kind"] == "image"
    assert rec["file"] == path.name == "IvanPetrov_face_imagex-1_001.png"
    assert rec["file_hash"] == sha(data)
    assert rec["pixel_hash"] == png_meta["pixel_hash"]
    assert rec["refs"] == png_meta["refs"]


def test_existing_json_is_never_overwritten(tmp_path):
    from comfy_openrouter import metadata

    (tmp_path / "x_001.json").write_text("keep me", encoding="utf-8")
    path = metadata.save_with_recipe(tmp_path, "x_{counter}", {}, b"data", ".mp3",
                                     {"schema": "openrouter-meta/1"}, "audio")
    assert path.read_bytes() == b"data"
    assert (tmp_path / "x_001.json").read_text(encoding="utf-8") == "keep me"


# -- Speak ----------------------------------------------------------------------------


SPEAK = {"voice": "nova", "format": "mp3", "speed": 1.0, "instructions": ""}


def test_speak_sends_only_set_fields_and_saves_mp3(tmp_path):
    fake = FakeTransport()
    audio, info = s.speak(client_with(fake), SPEECH, "Hello", SPEAK)
    assert audio == FAKE_MP3
    assert fake.posts()[0][3] == {"model": "fake/tts-1", "input": "Hello",
                                  "response_format": "mp3", "voice": "nova"}
    path = s.save_speech(audio, "mp3", info, "Hello", CONTEXT, "intro", tmp_path, PATTERN)
    assert path.name == "IvanPetrov_intro_tts-1_001.mp3" and path.read_bytes() == FAKE_MP3
    rec = recipe(path)
    assert rec["kind"] == "audio" and rec["pixel_hash"] is None and rec["cost_usd"] is None
    assert rec["prompt"] == "Hello" and rec["file_hash"] == sha(FAKE_MP3)
    assert rec["params"] == {"response_format": "mp3", "voice": "nova"}


def test_speak_pcm_saved_as_wav_with_speed_and_instructions(tmp_path):
    fake = FakeTransport()
    settings = {**SPEAK, "format": "pcm", "speed": 1.25, "instructions": "calm"}
    audio, info = s.speak(client_with(fake), SPEECH, "Hi", settings)
    sent = fake.posts()[0][3]
    assert sent["speed"] == 1.25 and sent["instructions"] == "calm"
    path = s.save_speech(audio, "pcm", info, "Hi", None, "", tmp_path, PATTERN)
    assert path.suffix == ".wav"
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24000, 1, 4)


def test_speak_empty_text():
    with pytest.raises(ValueError, match="Text is empty"):
        s.speak(client_with(FakeTransport()), SPEECH, " ", SPEAK)


# -- Video ----------------------------------------------------------------------------


VIDEO_SETTINGS = {"aspect_ratio": "16:9", "resolution": "1080p", "duration": 5,
                  "generate_audio": "on", "seed": 3}


def test_video_payload_drops_unsupported_values_and_sends_frames():
    payload, info, warnings = v.video_payload(VIDEO, "walks", VIDEO_SETTINGS,
                                              [("first_frame", FRAME)])
    assert payload["aspect_ratio"] == "16:9" and payload["generate_audio"] is True
    assert "resolution" not in payload and "duration" not in payload
    assert "resolution=1080p" in warnings[0] and "duration=5" in warnings[0]
    frame = payload["frame_images"][0]
    assert frame["frame_type"] == "first_frame" and frame["type"] == "image_url"
    assert frame["image_url"]["url"].startswith("data:image/png;base64,")
    assert info["refs"] == [{"pixel_hash": pixel_hash(FRAME), "width": 2, "height": 1,
                             "frame_type": "first_frame"}]


def test_video_auto_and_zero_are_not_sent():
    settings = {"aspect_ratio": "auto", "resolution": "auto", "duration": 0,
                "generate_audio": "auto", "seed": 0}
    payload, _, warnings = v.video_payload(VIDEO, "p", settings, [])
    assert payload == {"model": "fake/video-1", "seed": 0, "prompt": "p"}
    assert warnings == []


def test_video_needs_prompt_or_frame():
    settings = {**VIDEO_SETTINGS, "resolution": "720p", "duration": 4}
    with pytest.raises(ValueError, match="Prompt is empty"):
        v.video_payload(VIDEO, "", settings, [])
    payload, _, _ = v.video_payload(VIDEO, "", settings, [("first_frame", FRAME)])
    assert "prompt" not in payload


def test_video_submit_poll_download_and_save(tmp_path):
    fake, sleeps = FakeTransport(), []
    data, info, _ = v.make_video(client_with(fake, sleeps), VIDEO, "walks", VIDEO_SETTINGS,
                                 [("first_frame", FRAME)])
    assert data == FAKE_MP4 and info["cost_usd"] == 0.5
    urls = [c[1].split("/api/v1")[1] for c in fake.calls]
    assert urls == ["/videos", "/videos/gen-vid-1", "/videos/gen-vid-1",
                    "/videos/gen-vid-1/content?index=0"]
    assert len(sleeps) == 20  # 2 polls x 10 one-second waits
    path = v.save_video(data, info, "walks", CONTEXT, "walk", tmp_path, PATTERN)
    assert path.name == "IvanPetrov_walk_video-1_001.mp4"
    rec = recipe(path)
    assert rec["kind"] == "video" and rec["cost_usd"] == 0.5 and rec["pixel_hash"] is None
    assert rec["refs"][0]["pixel_hash"] == pixel_hash(FRAME)
    assert rec["file_hash"] == sha(FAKE_MP4)


def test_failed_video_job_raises():
    fake = FakeTransport(video_states=["failed"])
    with pytest.raises(OpenRouterError, match="failed: content policy"):
        v.make_video(client_with(fake), VIDEO, "p", VIDEO_SETTINGS, [])


def test_cancel_stops_waiting_without_download():
    fake = FakeTransport()

    def cancel():
        raise InterruptedError("cancelled by user")

    with pytest.raises(InterruptedError):
        v.make_video(client_with(fake), VIDEO, "p", VIDEO_SETTINGS, [], check_cancel=cancel)
    assert [c[1].split("/api/v1")[1] for c in fake.calls] == ["/videos"]


def test_video_timeout():
    fake = FakeTransport(video_states=["in_progress"] * 5)
    with pytest.raises(OpenRouterError, match="not finished"):
        client_with(fake).video({"model": "fake/video-1", "prompt": "p"}, poll=1, timeout=2)


# -- node definitions, model lists, binary transport ----------------------------------


@pytest.fixture
def no_models(monkeypatch):
    monkeypatch.setattr(model_list, "get_models",
                        lambda client=None, refresh=False, kind="image": ([], None))
    monkeypatch.setattr(model_list, "load_favorites", lambda: [])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def test_speak_and_video_node_definitions(no_models):
    speak, video = s.OpenRouterSpeak.INPUT_TYPES(), v.OpenRouterVideo.INPUT_TYPES()
    assert speak["required"]["text"] == ("STRING", {"forceInput": True})
    assert set(speak["optional"]) == {"context", "folder"}
    assert s.OpenRouterSpeak.RETURN_TYPES == ("AUDIO", "STRING")
    assert video["required"]["prompt"] == ("STRING", {"forceInput": True})
    assert set(video["optional"]) == {"context", "first_frame", "last_frame", "folder"}
    assert v.OpenRouterVideo.RETURN_TYPES == ("STRING", "STRING")
    assert s.OpenRouterSpeak.OUTPUT_NODE and v.OpenRouterVideo.OUTPUT_NODE
    assert video["required"]["model"][0] == [g.NO_MODELS]


def test_video_and_speech_model_lists(tmp_path):
    client = client_with(FakeTransport())
    vids, _ = model_list.get_models(client, cache_path=tmp_path / "v.json", kind="video")
    tts, _ = model_list.get_models(client, cache_path=tmp_path / "s.json", kind="speech")
    assert [m["id"] for m in vids] == ["fake/video-1"]
    assert [m["id"] for m in tts] == ["fake/tts-1"]


def test_urllib_transport_returns_bytes_for_audio():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(FAKE_MP3)))
            self.end_headers()
            self.wfile.write(FAKE_MP3)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
        client = OpenRouterClient("k", base_url=url, timeout=5)
        assert client.speech({"model": "a/b", "input": "x"}) == FAKE_MP3
    finally:
        server.shutdown()
        server.server_close()


def test_speak_explains_missing_voice():
    class NeedsVoice(FakeTransport):
        def __call__(self, method, url, headers, body, timeout):
            if url.endswith("/audio/speech"):
                return 400, {"error": {"message": "An explicit voice is required"}}
            return super().__call__(method, url, headers, body, timeout)

    settings = {**SPEAK, "voice": ""}
    with pytest.raises(OpenRouterError, match="openrouter.ai") as info:
        s.speak(client_with(NeedsVoice()), SPEECH, "Hi", settings)
    assert "fake/tts-1 has no default voice" in str(info.value)


def test_speak_language_widget_is_first(no_models):
    required = list(s.OpenRouterSpeak.INPUT_TYPES()["required"])
    assert required[:3] == ["text", "language", "model"]
