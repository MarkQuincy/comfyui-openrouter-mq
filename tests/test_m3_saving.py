"""M3: file names, never overwrite, PNG chunks, pixel hashes and refs."""

import json
from datetime import date, datetime, timezone

import pytest

import pngread
from comfy_openrouter import generate_node as g
from comfy_openrouter import metadata, naming
from comfy_openrouter.client import OpenRouterClient
from comfy_openrouter.images import encode_png, pixel_hash
from fakes import FAKE_MODELS, FakeTransport

IMAGEX = FAKE_MODELS[0]
PATTERN = naming.DEFAULT_PATTERN
FIELDS = {"date": "2026-11-16", "project": "ProjectX", "person": "Ivan Petrov",
          "name": "fullbody", "model": "gemini-3-pro-image"}
OUT = (3, 2, "RGB", bytes(range(18)))  # 3x2 RGB
REF = (2, 1, "RGB", bytes([255, 0, 0, 0, 0, 255]))


# -- naming ----------------------------------------------------------------------


def test_default_pattern_matches_spec_example():
    assert naming.render(PATTERN, FIELDS, 3) == \
        "2026-11-16_ProjectX_IvanPetrov_fullbody_gemini-3-pro-image_003"


def test_empty_parts_dropped_and_unsafe_chars_replaced():
    fields = {"date": "2026-11-16", "project": "", "person": 'A/B:C*?"<>|',
              "name": "  ", "model": "m"}
    assert naming.render(PATTERN, fields, 1) == "2026-11-16_A-B-C------_m_001"
    assert naming.render("{project}", {}, 1) == "image"
    assert naming.render("{date}_{model}.png", FIELDS, 1) == "2026-11-16_gemini-3-pro-image"


def test_never_overwrites(tmp_path):
    first = naming.save_new(tmp_path, PATTERN, FIELDS, b"one")
    second = naming.save_new(tmp_path, PATTERN, FIELDS, b"two")
    assert first.name.endswith("_001.png") and second.name.endswith("_002.png")
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"


def test_never_overwrites_without_counter_in_pattern(tmp_path):
    a = naming.save_new(tmp_path, "{name}", FIELDS, b"a")
    b = naming.save_new(tmp_path, "{name}", FIELDS, b"b")
    assert (a.name, b.name) == ("fullbody.png", "fullbody_002.png")
    assert a.read_bytes() == b"a"


def test_settings_file_created_with_default_and_editable(tmp_path):
    path = tmp_path / "settings.json"
    assert naming.load_settings(path)["filename_pattern"] == PATTERN
    assert json.loads(path.read_text(encoding="utf-8"))["filename_pattern"] == PATTERN
    path.write_text(json.dumps({"filename_pattern": "{person}_{counter}"}), encoding="utf-8")
    assert naming.load_settings(path)["filename_pattern"] == "{person}_{counter}"
    path.write_text("{broken", encoding="utf-8")
    assert naming.load_settings(path)["filename_pattern"] == PATTERN


# -- PNG and hashes ---------------------------------------------------------------


def test_png_round_trip_and_hash():
    png = encode_png(OUT, {"k": "v"})
    assert pngread.pixels(png) == OUT
    assert pngread.text(png) == {"k": "v"}
    assert pixel_hash(pngread.pixels(png)) == pixel_hash(OUT)
    assert pixel_hash(OUT).startswith("sha256:") and len(pixel_hash(OUT)) == 7 + 64


def test_hash_depends_on_size_and_mode():
    same_bytes_other_shape = (2, 3, "RGB", OUT[3])
    assert pixel_hash(OUT) != pixel_hash(same_bytes_other_shape)


def test_encode_rejects_wrong_size():
    with pytest.raises(ValueError):
        encode_png((2, 2, "RGB", b"\x00" * 5))


# -- metadata and saving ---------------------------------------------------------


def run_and_save(tmp_path, monkeypatch, refs=(REF,)):
    monkeypatch.setenv("OPENROUTER_USER", "alice")
    client = OpenRouterClient("secret-test-key", transport=FakeTransport(),
                              sleep=lambda s: None)
    settings = {"aspect_ratio": "3:4", "resolution": "auto", "quality": "high", "seed": 1234}
    _, info, _ = g.generate(client, IMAGEX, "Портрет, studio light", settings, list(refs))
    context = {"project": "ProjectX", "person": "Ivan Petrov"}
    graph = {"12": {"class_type": "OpenRouterGenerate", "inputs": {}}}
    extra = {"workflow": {"nodes": [{"id": 12}], "links": []}}
    paths = g.save_outputs([OUT], info, "Портрет, studio light", context, "fullbody",
                           tmp_path, PATTERN, graph, extra, node_id=12, prompt_id="abc")
    return paths, graph, extra


def test_saved_png_has_comfy_chunks_and_openrouter_meta(tmp_path, monkeypatch):
    (path,), graph, extra = run_and_save(tmp_path, monkeypatch)
    today = date.today().isoformat()
    assert path.name == f"{today}_ProjectX_IvanPetrov_fullbody_imagex-1_001.png"

    data = path.read_bytes()
    chunks = pngread.text(data)
    assert json.loads(chunks["prompt"]) == graph
    assert json.loads(chunks["workflow"]) == extra["workflow"]

    meta = json.loads(chunks["openrouter"])
    assert meta["schema"] == "openrouter-meta/1"
    assert meta["author"] == "alice"
    assert (meta["project"], meta["person"], meta["name"]) == ("ProjectX", "Ivan Petrov",
                                                               "fullbody")
    assert meta["model"] == "fake/imagex-1"
    assert meta["prompt"] == "Портрет, studio light"  # non-Latin survives (ASCII JSON)
    assert meta["params"] == {"aspect_ratio": "3:4", "quality": "high", "seed": 1234}
    assert meta["params_sent"] == ["aspect_ratio", "quality", "seed"]
    assert meta["cost_usd"] == 0.04
    assert meta["node_id"] == "12" and meta["comfyui_prompt_id"] == "abc"
    datetime.fromisoformat(meta["created_at"])  # valid ISO with offset
    assert set(meta) == {"schema", "created_at", "author", "project", "person", "name",
                         "model", "prompt", "params", "params_sent", "cost_usd",
                         "pixel_hash", "refs", "node_id", "comfyui_prompt_id"}

    # Lineage: hash of the saved file's decoded pixels equals the stored hash.
    assert pixel_hash(pngread.pixels(data)) == meta["pixel_hash"]
    assert meta["refs"] == [{"pixel_hash": pixel_hash(REF), "width": 2, "height": 1}]


def test_child_ref_hash_equals_parent_output_hash(tmp_path, monkeypatch):
    (parent,), _, _ = run_and_save(tmp_path, monkeypatch)
    parent_meta = json.loads(pngread.text(parent.read_bytes())["openrouter"])
    # The child uses the parent's saved pixels as its reference (like Load Image).
    (child,), _, _ = run_and_save(tmp_path, monkeypatch,
                                  refs=[pngread.pixels(parent.read_bytes())])
    child_meta = json.loads(pngread.text(child.read_bytes())["openrouter"])
    assert child_meta["refs"][0]["pixel_hash"] == parent_meta["pixel_hash"]
    assert child.name.endswith("_002.png")


def test_api_key_never_in_file(tmp_path, monkeypatch):
    (path,), _, _ = run_and_save(tmp_path, monkeypatch)
    assert b"secret-test-key" not in path.read_bytes()


def test_meta_without_context_or_ids():
    info = {"model": "a/b", "params": {}, "params_sent": [], "cost_usd": None, "refs": []}
    meta = metadata.build(info, "p", None, "", "sha256:x", [],
                          created_at=datetime(2026, 11, 16, 14, 3, 22, tzinfo=timezone.utc))
    assert meta["project"] == "" and meta["person"] == "" and meta["node_id"] is None
    assert meta["created_at"] == "2026-11-16T14:03:22+00:00"


def test_output_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_OUTPUT_DIR", str(tmp_path))
    assert g.output_dir() == tmp_path
    assert g.output_dir("  ") == tmp_path


def test_folder_box_subfolder_or_full_path(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_OUTPUT_DIR", str(tmp_path))
    assert g.output_dir("ProjectX\\portraits") == tmp_path / "ProjectX" / "portraits"
    other = tmp_path.parent / "elsewhere"
    assert g.output_dir(f'"{other}"') == other  # pasted with quotes, full path as is


def test_folder_box_is_optional_widget(monkeypatch):
    from comfy_openrouter import models as model_list
    monkeypatch.setattr(model_list, "get_models", lambda client=None, refresh=False: ([], None))
    monkeypatch.setattr(model_list, "load_favorites", lambda: [])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    kind, options = g.OpenRouterGenerate.INPUT_TYPES()["optional"]["folder"]
    assert kind == "STRING" and options["default"] == ""


def test_generate_node_is_output_node_with_hidden_inputs(monkeypatch, tmp_path):
    from comfy_openrouter import models as model_list
    monkeypatch.setattr(model_list, "get_models", lambda client=None, refresh=False: ([], None))
    monkeypatch.setattr(model_list, "load_favorites", lambda: [])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    hidden = g.OpenRouterGenerate.INPUT_TYPES()["hidden"]
    assert hidden == {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT",
                      "extra_pnginfo": "EXTRA_PNGINFO"}
    assert g.OpenRouterGenerate.OUTPUT_NODE is True
