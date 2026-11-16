"""File names from a pattern, ``user/settings.json``, and never-overwrite saving."""

import re
from pathlib import Path

from .models import USER_DIR, _read_json, _write_json

SETTINGS_FILE = USER_DIR / "settings.json"
DEFAULT_PATTERN = "{date}_{project}_{person}_{name}_{model}_{counter}"
DEFAULT_SETTINGS = {"filename_pattern": DEFAULT_PATTERN}

FIELD = re.compile(r"\{(\w+)\}")
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_PART = 60


def load_settings(path=SETTINGS_FILE):
    """Settings merged over defaults. Creates the file on first use."""
    path = Path(path)
    if not path.exists():
        _write_json(path, DEFAULT_SETTINGS)
    data = _read_json(path, {})
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS
                         and isinstance(v, str) and v.strip()})
    return settings


def clean(value):
    """Safe file name part: no spaces, no characters Windows forbids."""
    text = re.sub(r"\s+", "", str(value or ""))
    text = UNSAFE.sub("-", text).strip(" .")
    return text[:MAX_PART]


def render(pattern, fields, counter):
    """Fill the pattern. ``_``-separated parts that come out empty are dropped."""
    pattern = pattern[:-4] if pattern.lower().endswith(".png") else pattern

    def fill(match):
        key = match.group(1)
        return f"{counter:03d}" if key == "counter" else clean(fields.get(key, ""))

    parts = [FIELD.sub(fill, part) for part in pattern.split("_")]
    name = "_".join(p for p in parts if p) or "image"
    return name


def save_new(folder, pattern, fields, data):
    """Write ``data`` to a new ``.png`` in ``folder``; never overwrites. Returns the path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    has_counter = "{counter}" in pattern
    for counter in range(1, 100000):
        name = render(pattern, fields, counter)
        if not has_counter and counter > 1:
            name = f"{name}_{counter:03d}"
        path = folder / f"{name}.png"
        try:
            with open(path, "xb") as fh:  # "x" fails if the file exists
                fh.write(data)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"No free file name for {pattern!r} in {folder}")
