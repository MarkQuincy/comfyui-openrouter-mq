"""Cost report: add up ``cost_usd`` from saved recipes, grouped by a field.

Reads ``.json`` recipes (``openrouter-meta/2``) and, for older images without one,
the ``openrouter`` chunk inside the PNG. Never writes anything.
"""

import json
from pathlib import Path

from .images import read_png_text

GROUPS = ["project", "person", "model", "kind", "date", "author"]


def collect(folder):
    """All recipes under ``folder`` (recursive) as dicts."""
    folder = Path(folder)
    records = []
    for path in sorted(folder.rglob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and str(meta.get("schema", "")).startswith("openrouter-meta"):
            records.append(meta)
    for path in sorted(folder.rglob("*.png")):
        if path.with_suffix(".json").exists():
            continue  # already counted from its recipe
        try:
            meta = json.loads(read_png_text(path.read_bytes()).get("openrouter", ""))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict):
            records.append({**meta, "kind": "image"})
    return records


def group_value(meta, group_by):
    if group_by == "date":
        return str(meta.get("created_at") or "")[:10] or "(no date)"
    if group_by == "kind":
        return meta.get("kind") or "image"
    return str(meta.get(group_by) or "") or "(empty)"


def summarize(records, group_by="project", since=""):
    """Rows ``(group, files, total_usd, files_without_cost)``, biggest cost first."""
    rows = {}
    for meta in records:
        if since and str(meta.get("created_at") or "")[:10] < since:
            continue
        key = group_value(meta, group_by)
        files, total, unknown = rows.get(key, (0, 0.0, 0))
        cost = meta.get("cost_usd")
        if isinstance(cost, (int, float)):
            total += cost
        else:
            unknown += 1
        rows[key] = (files + 1, total, unknown)
    return sorted(((k, *v) for k, v in rows.items()), key=lambda r: (-r[2], r[0]))


def format_report(rows, group_by):
    if not rows:
        return "No OpenRouter files found."
    lines = [f"Cost by {group_by}:"]
    for key, files, total, unknown in rows:
        note = f"  ({unknown} without cost)" if unknown else ""
        lines.append(f"{key}: ${total:.4f} · {files} file(s){note}")
    all_files = sum(r[1] for r in rows)
    lines.append(f"TOTAL: ${sum(r[2] for r in rows):.4f} · {all_files} file(s)")
    return "\n".join(lines)
