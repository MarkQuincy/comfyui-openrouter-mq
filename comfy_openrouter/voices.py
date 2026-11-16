"""Voice lists for the Speak node's dropdown, with male/female marks where known.

Voice names come from the model's ``supported_voices``. When OpenRouter lists none,
the list comes from ``user/model_voices.json`` (``{"model id or prefix/": [names]}``)
or a small built-in list (ElevenLabs, from its model page on openrouter.ai).
Gender comes from, in order: ``user/voices.json`` (the user's own marks), a ``gender``
field from the provider, the built-in list, or a clear naming rule. Otherwise unknown.
"""

import re
from pathlib import Path

from . import models as model_list
from .models import USER_DIR, _read_json, _write_json

VOICES_FILE = USER_DIR / "voices.json"
MODEL_VOICES_FILE = USER_DIR / "model_voices.json"
# Voices listed on openrouter.ai/elevenlabs/eleven-v4; genders from ElevenLabs'
# voice library (river is described as neutral, so no mark).
BUILTIN = {
    "elevenlabs/": {
        "george": "male", "sarah": "female", "adam": "male", "alice": "female",
        "bella": "female", "bill": "male", "brian": "male", "callum": "male",
        "charlie": "male", "chris": "male", "daniel": "male", "eric": "male",
        "harry": "male", "jessica": "female", "laura": "female", "liam": "male",
        "lily": "female", "matilda": "female", "river": None, "roger": "male",
        "will": "male",
    },
}
ICONS = {"male": "♂ ", "female": "♀ "}
DEFAULT = "(model default)"
# Kokoro style: language letter + f/m + "_", e.g. af_bella = American female.
KOKORO = re.compile(r"^[a-z]([fm])_")


def load_marks(path=VOICES_FILE):
    """``{"voice id": "male" | "female"}``. Creates an empty file on first use."""
    path = Path(path)
    if not path.exists():
        _write_json(path, {})
        return {}
    data = _read_json(path, {})
    return {k: v for k, v in data.items() if v in ICONS} if isinstance(data, dict) else {}


def guess_gender(voice_id):
    match = KOKORO.match(voice_id)
    return {"f": "female", "m": "male"}[match.group(1)] if match else None


def load_model_voices(path=MODEL_VOICES_FILE):
    """``{"model id or prefix/": ["voice", ...]}``. Creates an empty file on first use."""
    path = Path(path)
    if not path.exists():
        _write_json(path, {})
        return {}
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return {}
    return {k: [x for x in v if isinstance(x, str)] for k, v in data.items()
            if isinstance(v, list)}


def fallback_voices(model_id, user_lists=None):
    """Voices for a model OpenRouter lists none for: user's file first, then built-in.
    Keys match the exact model id or a prefix ending in "/" (e.g. "elevenlabs/")."""
    def matches(key):
        return key == model_id or (key.endswith("/") and model_id.startswith(key))

    for key, names in (user_lists or {}).items():
        if matches(key):
            return [{"id": n, "gender": None} for n in names]
    for key, genders in BUILTIN.items():
        if matches(key):
            return [{"id": n, "gender": g} for n, g in genders.items()]
    return []


def voice_list(model_info, marks=None, user_lists=None):
    """``[{"id", "gender"}]`` from the model's ``supported_voices`` (strings or objects),
    or the fallback lists when it has none."""
    marks = marks or {}
    model_info = model_info or {}
    items = model_info.get("supported_voices") or \
        fallback_voices(model_info.get("id") or "", user_lists)
    out = []
    for item in items:
        if isinstance(item, dict):
            voice_id = item.get("id") or item.get("voice_id") or item.get("name")
            given = str(item.get("gender") or "").lower() or None
        else:
            voice_id, given = item, None
        if not isinstance(voice_id, str) or not voice_id:
            continue
        gender = marks.get(voice_id) or (given if given in ICONS else None) \
            or guess_gender(voice_id)
        out.append({"id": voice_id, "gender": gender})
    return out


def label(voice):
    return ICONS.get(voice["gender"], "") + voice["id"]


def voices_payload(model, cache_path=None, marks_path=VOICES_FILE,
                   lists_path=MODEL_VOICES_FILE):
    """For the route: ``{"labels": [...], "ids": [...]}`` for a model id or dropdown label.
    Reads only the cache (no network)."""
    models, _ = model_list.get_models(None, cache_path=cache_path, kind="speech")
    model_id = model_list.id_from_label(model or "")
    # Not in the cache: the fallback lists can still apply.
    info = model_list.find_model(models, model_id) or {"id": model_id}
    voices = voice_list(info, load_marks(marks_path), load_model_voices(lists_path))
    return {"labels": [DEFAULT] + [label(v) for v in voices],
            "ids": [""] + [v["id"] for v in voices]}
