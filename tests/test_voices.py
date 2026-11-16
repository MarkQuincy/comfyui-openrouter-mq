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
    data = v.voices_payload("kokoro / tts", cache_path=cache, marks_path=tmp_path / "m.json")
    assert data["labels"][:3] == ["(model default)", "♀ af_bella", "♂ am_adam"]
    assert data["ids"][:3] == ["", "af_bella", "am_adam"]
    unknown = v.voices_payload("nope / none", cache_path=cache, marks_path=tmp_path / "m.json")
    assert unknown == {"labels": ["(model default)"], "ids": [""]}


def test_js_has_voice_picker():
    js = (Path(__file__).resolve().parent.parent / "web" / "openrouter.js").read_text(
        encoding="utf-8")
    assert "/openrouter/voices?model=" in js and '"voice list"' in js
