"""Cost report from saved recipes (.json, and the PNG chunk for older images)."""

import json

from comfy_openrouter import report
from comfy_openrouter.images import encode_png, read_png_text
from comfy_openrouter.report_node import OpenRouterCostReport


def recipe(path, **meta):
    base = {"schema": "openrouter-meta/2", "created_at": "2026-11-16T10:00:00+03:00",
            "project": "P", "person": "Ivan", "model": "a/img", "kind": "image",
            "author": "alice", "cost_usd": 0.04}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**base, **meta}), encoding="utf-8")


def make_folder(tmp_path):
    recipe(tmp_path / "a_001.json")
    recipe(tmp_path / "a_002.json", kind="video", model="b/vid", cost_usd=0.5)
    recipe(tmp_path / "sub" / "c_001.json", kind="audio", project="Q", cost_usd=None)
    recipe(tmp_path / "old.json", created_at="2026-10-01T09:00:00+03:00", cost_usd=1.0)
    (tmp_path / "notes.json").write_text('{"x": 1}', encoding="utf-8")  # not a recipe
    (tmp_path / "broken.json").write_text("{nope", encoding="utf-8")
    # Older PNG without a .json: read from its chunk.
    meta = {"schema": "openrouter-meta/1", "created_at": "2026-11-15T09:00:00+03:00",
            "project": "P", "model": "a/img", "cost_usd": 0.03}
    png = encode_png((1, 1, "RGB", b"\0\0\0"), {"openrouter": json.dumps(meta)})
    (tmp_path / "legacy.png").write_bytes(png)
    # PNG that has a .json: counted once, from the .json.
    (tmp_path / "a_001.png").write_bytes(encode_png((1, 1, "RGB", b"\0\0\0"),
                                                    {"openrouter": json.dumps(meta)}))


def test_collect_reads_recipes_and_old_pngs_once(tmp_path):
    make_folder(tmp_path)
    records = report.collect(tmp_path)
    assert len(records) == 5  # 4 recipes + legacy.png
    assert sum(1 for r in records if r["kind"] == "image") == 3


def test_summary_by_kind_and_unknown_costs(tmp_path):
    make_folder(tmp_path)
    rows = report.summarize(report.collect(tmp_path), "kind")
    assert rows == [("image", 3, 1.07, 0), ("video", 1, 0.5, 0), ("audio", 1, 0.0, 1)]
    text = report.format_report(rows, "kind")
    assert "video: $0.5000 · 1 file(s)" in text
    assert "audio: $0.0000 · 1 file(s)  (1 without cost)" in text
    assert text.endswith("TOTAL: $1.5700 · 5 file(s)")


def test_summary_since_and_by_date(tmp_path):
    make_folder(tmp_path)
    records = report.collect(tmp_path)
    rows = report.summarize(records, "date", since="2026-11-01")
    assert [r[0] for r in rows] == ["2026-11-16", "2026-11-15"]
    assert sum(r[1] for r in rows) == 4  # the October file is left out


def test_empty_folder(tmp_path):
    assert report.format_report(report.summarize(report.collect(tmp_path)), "project") == \
        "No OpenRouter files found."


def test_node_runs_on_a_folder(tmp_path, monkeypatch):
    make_folder(tmp_path)
    monkeypatch.setenv("OPENROUTER_OUTPUT_DIR", str(tmp_path))
    out = OpenRouterCostReport().run("model", "")
    assert out["result"][0] == out["ui"]["openrouter_report"][0]
    assert "b/vid: $0.5000" in out["result"][0]
    assert OpenRouterCostReport.OUTPUT_NODE is True


def test_read_png_text():
    png = encode_png((1, 1, "RGB", b"\0\0\0"), {"k": "v", "openrouter": "{}"})
    assert read_png_text(png) == {"k": "v", "openrouter": "{}"}
    assert read_png_text(b"not a png") == {}
