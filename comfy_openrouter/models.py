"""Model list: cache file, favorites file, dropdown sort order and labels.

Files live in ``user/`` next to the node (git-ignored, created on first use).
"""

import json
import time
from pathlib import Path

from .client import OpenRouterError, outputs_images

USER_DIR = Path(__file__).resolve().parent.parent / "user"
FAVORITES_FILE = USER_DIR / "favorites.json"
CACHE_FILE = USER_DIR / "models_cache.json"
STAR = "★ "


# -- files -------------------------------------------------------------------------


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_favorites(path=FAVORITES_FILE):
    """Favorite model ids. Creates an empty file on first use so the user can edit it."""
    path = Path(path)
    if not path.exists():
        _write_json(path, [])
        return []
    data = _read_json(path, [])
    return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []


def save_favorites(ids, path=FAVORITES_FILE):
    _write_json(path, sorted(set(ids)))


def load_cache(path=CACHE_FILE):
    data = _read_json(path, {})
    models = data.get("data") if isinstance(data, dict) else None
    return models if isinstance(models, list) else []


def save_cache(models, path=CACHE_FILE):
    _write_json(path, {"fetched_at": int(time.time()), "data": models})


def get_models(client=None, refresh=False, cache_path=CACHE_FILE):
    """Image models: from the cache, or fetched when ``refresh`` or no cache yet.

    Works offline: without a client, or if the fetch fails, the cache is used.
    Returns ``(models, error)``; ``error`` is a message string or None.
    """
    cached = load_cache(cache_path)
    if client is None or (cached and not refresh):
        return image_models(cached), None
    try:
        fetched = client.list_models()
    except OpenRouterError as exc:
        return image_models(cached), f"model list refresh failed, using cache: {exc}"
    save_cache(fetched, cache_path)
    return image_models(fetched), None


# -- sorting and labels ----------------------------------------------------------


def image_models(models):
    return [m for m in models if isinstance(m, dict) and m.get("id") and outputs_images(m)]


def family(model_id):
    """Author part of the id: ``google/gemini-3-pro-image`` -> ``google``."""
    return model_id.split("/", 1)[0].lower()


def sort_models(models, favorites=()):
    """Family A->Z, then favorites first, then newest ``created`` first."""
    favs = set(favorites)

    def key(m):
        created = m.get("created") if isinstance(m.get("created"), (int, float)) else 0
        return (family(m["id"]), m["id"] not in favs, -created, m["id"])

    return sorted(models, key=key)


def label(model_id, favorites=()):
    """Dropdown label, e.g. ``★ google / gemini-3-pro-image``."""
    author, _, name = model_id.partition("/")
    text = f"{author} / {name}" if name else model_id
    return STAR + text if model_id in set(favorites) else text


def id_from_label(text):
    """Inverse of ``label`` (also accepts a plain model id)."""
    if text.startswith(STAR):
        text = text[len(STAR):]
    return text.replace(" / ", "/", 1)


def dropdown(models, favorites=()):
    """Sorted dropdown labels for the Generate node."""
    return [label(m["id"], favorites) for m in sort_models(models, favorites)]


def find_model(models, model_id):
    for m in models:
        if m.get("id") == model_id:
            return m
    return None
