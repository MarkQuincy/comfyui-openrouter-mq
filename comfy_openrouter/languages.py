"""Language filter for the Speak node's model dropdown.

OpenRouter has no language field for speech models. A model matches a language if
``user/languages.json`` lists it there (``{"speechify/simba-3.5": ["ru", "en"]}``) or
its description names the language. Models whose description only says
"multilingual" / "48 languages" match every language, with a mark in the dropdown.
"""

import re
from pathlib import Path

from . import models as model_list
from .models import MULTI_MARK, USER_DIR, _read_json, _write_json

LANGUAGES_FILE = USER_DIR / "languages.json"
ALL = "all"
# code -> (dropdown name, words that name the language in an English description)
LANGUAGES = {
    "en": ("English", ["english"]),
    "ru": ("Russian", ["russian"]),
    "uk": ("Ukrainian", ["ukrainian"]),
    "de": ("German", ["german"]),
    "fr": ("French", ["french"]),
    "es": ("Spanish", ["spanish"]),
    "it": ("Italian", ["italian"]),
    "pt": ("Portuguese", ["portuguese"]),
    "pl": ("Polish", ["polish"]),
    "tr": ("Turkish", ["turkish"]),
    "ar": ("Arabic", ["arabic"]),
    "hi": ("Hindi", ["hindi"]),
    "zh": ("Chinese", ["chinese", "mandarin", "cantonese"]),
    "ja": ("Japanese", ["japanese"]),
    "ko": ("Korean", ["korean"]),
}
MULTILINGUAL = re.compile(r"multilingual|multi-lingual|\b\d+\+?\s+languages", re.I)


def load_map(path=LANGUAGES_FILE):
    """``{"model id": ["ru", ...]}``. Creates an empty file on first use."""
    path = Path(path)
    if not path.exists():
        _write_json(path, {})
        return {}
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return {}
    return {k: [c for c in v if isinstance(c, str)] for k, v in data.items()
            if isinstance(v, list)}


def model_languages(model, lang_map=None):
    """``(set of codes, multilingual)`` for one speech model."""
    codes = set((lang_map or {}).get(model.get("id"), []))
    text = f"{model.get('name', '')} {model.get('description', '')}".lower()
    for code, (_, words) in LANGUAGES.items():
        if any(re.search(rf"\b{w}\b", text) for w in words):
            codes.add(code)
    return codes, bool(MULTILINGUAL.search(text))


def filtered_labels(models, language, favorites=(), lang_map=None):
    """Dropdown labels of models that suit ``language`` (``all`` = every model).
    Models matched only by "multilingual" get a mark."""
    if language == ALL:
        return model_list.dropdown(models, favorites)
    keep, multi_only = [], set()
    for m in models:
        codes, multi = model_languages(m, lang_map)
        if language in codes:
            keep.append(m)
        elif multi:
            keep.append(m)
            multi_only.add(m["id"])
    labels = model_list.dropdown(keep, favorites)
    return [lab + MULTI_MARK if model_list.id_from_label(lab) in multi_only else lab
            for lab in labels]


def speech_models_payload(language=ALL, cache_path=None, map_path=LANGUAGES_FILE):
    """For the route: languages for the filter and the matching model labels (cache only)."""
    models, _ = model_list.get_models(None, cache_path=cache_path, kind="speech")
    labels = filtered_labels(models, language or ALL, model_list.load_favorites(),
                             load_map(map_path))
    return {
        "languages": [{"code": ALL, "name": "All languages"}] +
                     [{"code": c, "name": f"{n} ({c})"} for c, (n, _) in LANGUAGES.items()],
        "labels": labels,
    }
