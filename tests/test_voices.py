"""Voice dropdown data: per-model voices, male/female from the user's file, provider
field or clear naming rule; unknown stays unmarked."""

import json
from pathlib import Path

from comfy_openrouter import models as model_list
from comfy_openrouter import voices as v

MODEL = {"id": "kokoro/tts", "supported_voices": [
    "af_bella", "am_adam", "alloy", {"id": "eve", "gender": "Female"}, {"name": "rex"}, 7, ""]}


def test_voice_list_genders():
    voices = v.voice_list(MODEL, {"alloy": "male"})
    assert voices == [
        {"id": "af_bella", "gender": "female"},  # naming rule
        {"id": "am_adam", "gender": "male"},
        {"id": "alloy", "gender": "male"},       # user's file
        {"id": "eve", "gender": "female"},       # provider field
        {"id": "rex", "gender": None},           # unknown: no icon
    ]
    assert [v.label(x) for x in voices] == ["♀ af_bella", "♂ am_adam", "♂ alloy",
                                            "♀ eve", "rex"]


def test_users_file_beats_guess_and_ignores_bad_values(tmp_path):
    path = tmp_path / "voices.json"
    assert v.load_marks(path) == {}  # created on first use
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    path.write_text(json.dumps({"af_bella": "male", "x": "robot"}), encoding="utf-8")
    marks = v.load_marks(path)
    assert marks == {"af_bella": "male"}
    assert v.voice_list({"supported_voices": ["af_bella"]}, marks)[0]["gender"] == "male"


def test_no_rule_for_ordinary_names():
    for name in ["alloy", "nova", "flux-alexis-en", "en_paul_happy", "a_b"]:
        assert v.guess_gender(name) is None


def test_model_without_voices():
    assert v.voice_list({"id": "x/y"}) == []
    assert v.voice_list(None) == []


def test_payload_from_cache_by_label(tmp_path):
    cache = tmp_path / "speech.json"
    model_list.save_cache([MODEL], cache)
    data = v.voices_payload("kokoro / tts", cache_path=cache, marks_path=tmp_path / "m.json",
                             lists_path=tmp_path / "l.json")
    assert data["labels"][:3] == ["(model default)", "♀ af_bella", "♂ am_adam"]
    assert data["ids"][:3] == ["", "af_bella", "am_adam"]
    unknown = v.voices_payload("nope / none", cache_path=cache, marks_path=tmp_path / "m.json",
                             lists_path=tmp_path / "l.json")
    assert unknown["labels"] == ["(model default)"] and unknown["ids"] == [""]
    assert unknown["cloning"].startswith("Voice cloning: not listed")


def test_js_has_voice_picker():
    js = (Path(__file__).resolve().parent.parent / "web" / "openrouter.js").read_text(
        encoding="utf-8")
    assert "/openrouter/voices?model=" in js and '"voice list"' in js


def test_builtin_elevenlabs_voices_when_openrouter_lists_none():
    voices = v.voice_list({"id": "elevenlabs/eleven-v4"})
    names = [x["id"] for x in voices]
    assert len(names) == 21 and names[0] == "george"
    assert v.label(voices[0]) == "♂ george" and v.label(voices[1]) == "♀ sarah"
    assert v.label(next(x for x in voices if x["id"] == "river")) == "river"  # neutral


def test_users_voice_list_beats_builtin_and_marks_still_apply(tmp_path):
    path = tmp_path / "model_voices.json"
    assert v.load_model_voices(path) == {}  # created on first use
    path.write_text('{"elevenlabs/eleven-v4": ["my-clone"], "acme/": ["a", 5]}',
                    encoding="utf-8")
    lists = v.load_model_voices(path)
    assert lists == {"elevenlabs/eleven-v4": ["my-clone"], "acme/": ["a"]}
    assert v.voice_list({"id": "elevenlabs/eleven-v4"}, user_lists=lists) == [
        {"id": "my-clone", "gender": None}]
    assert v.voice_list({"id": "acme/tts-2"}, {"a": "female"}, lists) == [
        {"id": "a", "gender": "female"}]


def test_supported_voices_win_over_fallback():
    model = {"id": "elevenlabs/new", "supported_voices": ["x"]}
    assert [x["id"] for x in v.voice_list(model)] == ["x"]


def test_payload_for_model_missing_from_cache_uses_builtin(tmp_path):
    data = v.voices_payload("elevenlabs / eleven-v4 · multilingual",
                            cache_path=tmp_path / "none.json", marks_path=tmp_path / "m.json",
                            lists_path=tmp_path / "l.json")
    assert data["ids"][:2] == ["", "george"] and data["labels"][1] == "♂ george"
