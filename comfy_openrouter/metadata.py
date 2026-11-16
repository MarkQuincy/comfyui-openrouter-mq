"""The ``openrouter`` PNG metadata (a contract for tools that read it, see SPEC)."""

import getpass
import hashlib
import json
import logging
import os
from datetime import datetime

from .naming import save_new

SCHEMA = "openrouter-meta/1"  # PNG chunk
RECIPE_SCHEMA = "openrouter-meta/2"  # JSON file next to every saved file

log = logging.getLogger("comfyui-openrouter")


def author():
    name = os.environ.get("OPENROUTER_USER", "").strip()
    if name:
        return name
    try:
        return getpass.getuser()
    except Exception:  # no user name available on this system
        return ""


def build(info, prompt, context, name, out_hash, refs, node_id=None, prompt_id=None,
          created_at=None):
    """Metadata dict for one saved image.

    ``info`` comes from ``generate_node.generate``; ``refs`` is a list of
    ``{"pixel_hash", "width", "height"}`` for the references actually sent.
    """
    context = context or {}
    created = created_at or datetime.now().astimezone()
    return {
        "schema": SCHEMA,
        "created_at": created.isoformat(timespec="seconds"),
        "author": author(),
        "project": context.get("project", ""),
        "person": context.get("person", ""),
        "name": name or "",
        "model": info["model"],
        "prompt": prompt,
        "params": info["params"],
        "params_sent": info["params_sent"],
        "cost_usd": info["cost_usd"],
        "pixel_hash": out_hash,
        "refs": refs,
        "node_id": None if node_id is None else str(node_id),
        "comfyui_prompt_id": prompt_id,
    }


def png_text(meta, prompt_graph=None, extra_pnginfo=None):
    """tEXt chunks like ComfyUI's Save Image (``prompt``, ``workflow``) + ``openrouter``.

    JSON is ASCII-only (``ensure_ascii``), so non-Latin prompts are safe in tEXt.
    """
    text = {}
    if prompt_graph is not None:
        text["prompt"] = json.dumps(prompt_graph)
    for key, value in (extra_pnginfo or {}).items():
        text[key] = json.dumps(value)
    text["openrouter"] = json.dumps(meta)
    return text


def save_with_recipe(folder, pattern, fields, data, ext, meta, kind):
    """Save ``data`` as a new file plus ``<same name>.json`` (the recipe). Returns the path."""
    path = save_new(folder, pattern, fields, data, ext)
    recipe = {**meta, "schema": RECIPE_SCHEMA, "kind": kind, "file": path.name,
              "file_hash": "sha256:" + hashlib.sha256(data).hexdigest()}
    try:
        with open(path.with_suffix(".json"), "x", encoding="utf-8") as fh:
            json.dump(recipe, fh, indent=2, ensure_ascii=False)
    except FileExistsError:  # never overwrite; the media file itself is saved
        log.warning("[OpenRouter] recipe not written, file exists: %s", path.with_suffix(".json"))
    return path
