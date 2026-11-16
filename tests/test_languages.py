"""Language filter for speech models: description words + user/languages.json;
"multilingual" models match every language with a mark."""

import json
from pathlib import Path

from comfy_openrouter import languages as lang
from comfy_openrouter import models as model_list

MODELS = [
    {"id": "speechify/simba-3.5", "description": "TTS covering 48 languages under one model."},
    {"id": "acme/ru-voice", "description": "Natural Russian and English speech."},
    {"id": "acme/en-only", "description": "Expressive English narration."},
    {"id": "acme/mystery", "description": "A speech model."},
    {"id": "acme/russet", "description": "Russet-toned English voices."},  # not "russian"
]


def test_model_languages():
    assert lang.model_languages(MODELS[0]) == (set(), True)
    assert lang.model_languages(MODELS[1]) == ({"ru", "en"}, False)
    assert lang.model_languages(MODELS[4]) == ({"en"}, False)
    assert lang.model_languages(MODELS[3], {"acme/mystery": ["ru"]}) == ({"ru"}, False)


def test_filter_russian():
    labels = lang.filtered_labels(MODELS, "ru")
    assert labels == ["acme / ru-voice", "speechify / simba-3.5 · multilingual"]


def test_filter_with_users_file_and_all():
    labels = lang.filtered_labels(MODELS, "ru", lang_map={"acme/mystery": ["ru"]})
    assert "acme / mystery" in labels and "acme / en-only" not in labels
    assert len(lang.filtered_labels(MODELS, "all")) == len(MODELS)


def test_marked_label_maps_back_to_id():
    assert model_list.id_from_label("★ speechify / simba-3.5 · multilingual") == \
        "speechify/simba-3.5"


def test_languages_file(tmp_path):
    path = tmp_path / "languages.json"
    assert lang.load_map(path) == {}
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    path.write_text(json.dumps({"a/b": ["ru", 5], "c/d": "ru"}), encoding="utf-8")
    assert lang.load_map(path) == {"a/b": ["ru"]}


def test_payload_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(model_list, "load_favorites", lambda: [])
    cache = tmp_path / "speech.json"
    model_list.save_cache(MODELS, cache)
    data = lang.speech_models_payload("English (en)", cache_path=cache,
                                      map_path=tmp_path / "l.json")
    assert data["labels"] == ["acme / en-only", "acme / ru-voice", "acme / russet",
                              "speechify / simba-3.5 · multilingual"]


def test_js_has_language_filter():
    js = (Path(__file__).resolve().parent.parent / "web" / "openrouter.js").read_text(
        encoding="utf-8")
    assert "/openrouter/speech_models?language=" in js and "hookLanguage" in js


def test_users_file_overrides_description():
    # AssemblyAI says "multilingual" but the user found it cannot speak Russian.
    model = {"id": "assemblyai/tts-1", "description": "Multilingual TTS"}
    assert lang.filtered_labels([model], "ru") == ["assemblyai / tts-1 · multilingual"]
    assert lang.filtered_labels([model], "ru", lang_map={"assemblyai/tts-1": ["en"]}) == []
    english = lang.filtered_labels([model], "en", lang_map={"assemblyai/tts-1": ["en"]})
    assert english == ["assemblyai / tts-1"]


def test_widget_choices():
    assert lang.choices()[0] == "All languages" and "Russian (ru)" in lang.choices()
    assert lang.code_from_choice("Russian (ru)") == "ru"
    assert lang.code_from_choice("ru") == "ru"
    assert lang.code_from_choice("All languages") == "all"
    assert lang.code_from_choice("Klingon (tlh)") == "all"
