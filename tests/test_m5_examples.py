"""M5: example workflows are consistent with the nodes and with their generator."""

import importlib.util
import json
from pathlib import Path

import pytest

from comfy_openrouter import generate_node as g
from comfy_openrouter import models as model_list

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
FILES = sorted(EXAMPLES.glob("*.json"))


def load_generator():
    spec = importlib.util.spec_from_file_location("make_examples",
                                                  EXAMPLES / "make_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_widget_names(monkeypatch):
    """Widget names of the Generate node in ComfyUI's order (seed adds a control)."""
    monkeypatch.setattr(model_list, "get_models", lambda client=None, refresh=False, kind="image": ([], None))
    monkeypatch.setattr(model_list, "load_favorites", lambda: [])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    types = g.OpenRouterGenerate.INPUT_TYPES()
    names = []
    for section in ("required", "optional"):
        for name, spec in types[section].items():
            kind = spec[0]
            options = spec[1] if len(spec) > 1 else {}
            is_widget = isinstance(kind, list) or (kind in ("STRING", "INT")
                                                   and not options.get("forceInput"))
            if is_widget:
                names.append(name)
                if options.get("control_after_generate"):
                    names.append("control_after_generate")
    return names


def test_examples_exist():
    assert [f.name for f in FILES] == ["01_single_person.json", "02_face_fullbody_tweak.json",
                                       "03_four_variants.json", "04_model_comparison.json",
                                       "05_speak.json", "06_portrait_to_video.json"]


def test_files_match_generator():
    gen = load_generator()
    for filename, build in gen.EXAMPLES.items():
        on_disk = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(build().to_json())), filename


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_links_are_consistent(path):
    wf = json.loads(path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in wf["nodes"]}
    assert wf["last_node_id"] == max(nodes) and wf["last_link_id"] == len(wf["links"])
    for link_id, src, src_slot, dst, dst_slot, type_ in wf["links"]:
        out = nodes[src]["outputs"][src_slot]
        inp = nodes[dst]["inputs"][dst_slot]
        assert link_id in out["links"] and inp["link"] == link_id
        assert out["type"] == inp["type"] == type_


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_generate_nodes_are_valid(path, monkeypatch):
    names = generate_widget_names(monkeypatch)
    assert names == ["model", "aspect_ratio", "resolution", "quality", "seed",
                     "control_after_generate", "name", "folder"]
    wf = json.loads(path.read_text(encoding="utf-8"))
    gens = [n for n in wf["nodes"] if n["type"] == "OpenRouterGenerate"]
    for node in gens:
        values = dict(zip(names, node["widgets_values"]))
        assert len(node["widgets_values"]) == len(names)
        assert values["aspect_ratio"] in g.ASPECT_RATIOS
        assert values["resolution"] in g.RESOLUTIONS and values["quality"] in g.QUALITIES
        assert values["control_after_generate"] == "randomize"
        assert values["name"]
        connected = {i["name"] for i in node["inputs"] if i["link"] is not None}
        assert {"prompt", "context", "ref_1"} <= connected


def test_no_key_in_examples():
    for path in FILES:
        assert "sk-or-" not in path.read_text(encoding="utf-8")
