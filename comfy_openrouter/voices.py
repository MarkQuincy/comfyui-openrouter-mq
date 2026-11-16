"""Voice lists for the Speak node's dropdown, with male/female marks where known.

OpenRouter gives only voice names (``supported_voices`` of a speech model). Gender
comes from, in order: ``user/voices.json`` (the user's own marks), a ``gender`` field
if the provider sends one, or a clear naming rule. Otherwise it stays unknown.
"""

import re
from pathlib import Path

from . import models as model_list
from .models import USER_DIR, _read_json, _write_json

VOICES_FILE = USER_DIR / "voices.json"
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


def voice_list(model_info, marks=None):
    """``[{"id", "gender"}]`` from the model's ``supported_voices`` (strings or objects)."""
    marks = marks or {}
    out = []
    for item in (model_info or {}).get("supported_voices") or []:
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


def voices_payload(model, cache_path=None, marks_path=VOICES_FILE):
    """For the route: ``{"labels": [...], "ids": [...]}`` for a model id or dropdown label.
    Reads only the cache (no network)."""
    models, _ = model_list.get_models(None, cache_path=cache_path, kind="speech")
    info = model_list.find_model(models, model_list.id_from_label(model or ""))
    voices = voice_list(info, load_marks(marks_path))
    return {"labels": [DEFAULT] + [label(v) for v in voices],
            "ids": [""] + [v["id"] for v in voices]}
