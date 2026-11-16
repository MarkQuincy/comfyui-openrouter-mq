"""M2: Context and Generate nodes (logic on PNG bytes, fake transport, no torch)."""

import base64

import pytest

from comfy_openrouter import generate_node as g
from comfy_openrouter import models as model_list
from comfy_openrouter.client import NoCreditsError, OpenRouterClient
from comfy_openrouter.context_node import OpenRouterContext
from comfy_openrouter.images import encode_png, pixel_hash
from fakes import FAKE_MODELS, TINY_PNG, FakeTransport

IMAGEX, TEXT_ONLY = FAKE_MODELS
REF = (2, 1, "RGB", bytes([255, 0, 0, 0, 0, 255]))  # 2x1 pixels: red, blue
SETTINGS = {"aspect_ratio": "3:4", "resolution": "auto", "quality": "high", "seed": 42}


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """Point the cache and favorites files at a temp folder."""
    monkeypatch.setattr(model_list, "CACHE_FILE", tmp_path / "image_models_cache.json")
    monkeypatch.setattr(model_list, "FAVORITES_FILE", tmp_path / "favorites.json")
    # get_models/load_favorites take the path as a default argument: rebind them.
    real_get, real_fav = model_list.get_models, model_list.load_favorites
    monkeypatch.setattr(model_list, "get_models", lambda client=None, refresh=False,
                        kind="image": real_get(client, refresh,
                                               tmp_path / f"{kind}_models_cache.json", kind))
    monkeypatch.setattr(model_list, "load_favorites",
                        lambda: real_fav(tmp_path / "favorites.json"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return tmp_path


def client_with(fake):
    return OpenRouterClient("k", transport=fake, sleep=lambda s: None)


def test_context_node():
    assert OpenRouterContext.RETURN_TYPES == ("OR_CONTEXT",)
    assert OpenRouterContext().run(" ProjectX ", "Ivan Petrov ") == (
        {"project": "ProjectX", "person": "Ivan Petrov"},)


def test_generate_node_definition(user_dir):
    model_list.save_cache(FAKE_MODELS, user_dir / "image_models_cache.json")
    model_list.save_favorites(["fake/text-only"], user_dir / "favorites.json")
    inputs = g.OpenRouterGenerate.INPUT_TYPES()
    req, opt = inputs["required"], inputs["optional"]
    assert req["prompt"] == ("STRING", {"forceInput": True})
    assert req["model"][0] == ["★ fake / text-only", "fake / imagex-1"]
    assert req["seed"][1]["control_after_generate"] is True
    assert {"aspect_ratio", "resolution", "quality", "name"} <= set(req)
    assert set(opt) == {"context", "ref_1", "ref_2", "ref_3", "ref_4", "folder"}
    assert opt["ref_1"] == ("IMAGE",) and opt["context"] == ("OR_CONTEXT",)
    assert g.OpenRouterGenerate.RETURN_TYPES == ("IMAGE", "STRING")


def test_dropdown_without_key_or_cache(user_dir):
    assert g.OpenRouterGenerate.INPUT_TYPES()["required"]["model"][0] == [g.NO_MODELS]
    assert g.OpenRouterGenerate.VALIDATE_INPUTS(g.NO_MODELS) != True  # noqa: E712
    assert g.OpenRouterGenerate.VALIDATE_INPUTS("★ old / label") is True


def test_first_start_with_key_fetches_list(user_dir):
    fake = FakeTransport()
    assert g.model_choices(client_with(fake)) == ["fake / imagex-1", "fake / text-only"]
    assert (user_dir / "image_models_cache.json").exists()


def test_generate_sends_supported_params_and_refs():
    fake = FakeTransport()
    images, info, warnings = g.generate(client_with(fake), IMAGEX, "a portrait",
                                        SETTINGS, [REF])
    sent = fake.posts()[0][3]
    assert images == [TINY_PNG]
    assert sent["aspect_ratio"] == "3:4" and sent["quality"] == "high" and sent["seed"] == 42
    assert "resolution" not in sent  # "auto" is never sent
    url = sent["input_references"][0]["image_url"]["url"]
    assert url == "data:image/png;base64," + base64.b64encode(encode_png(REF)).decode()
    assert info == {"model": "fake/imagex-1", "cost_usd": 0.04, "seed": 42,
                    "params": {"aspect_ratio": "3:4", "quality": "high", "seed": 42},
                    "params_sent": ["aspect_ratio", "quality", "seed"], "refs_sent": 1,
                    "refs": [{"pixel_hash": pixel_hash(REF), "width": 2, "height": 1}]}
    assert warnings == []


def test_unsupported_params_dropped_with_warning():
    fake = FakeTransport()
    _, info, warnings = g.generate(client_with(fake), TEXT_ONLY, "p", SETTINGS, [REF])
    # 3:4 is not in this model's values ["1:1"], so aspect_ratio is dropped too.
    assert fake.posts()[0][3] == {"model": "fake/text-only", "prompt": "p"}
    assert info["params_sent"] == [] and info["refs_sent"] == 0
    assert any("not sent: aspect_ratio, quality, seed" in w for w in warnings)
    assert any("accepts 0" in w for w in warnings)


def test_refs_capped_per_model_with_warning():
    fake = FakeTransport()
    _, info, warnings = g.generate(client_with(fake), IMAGEX, "p", SETTINGS,
                                   [REF] * 5)
    assert len(fake.posts()[0][3]["input_references"]) == 2
    assert info["refs_sent"] == 2
    assert any("5 reference images given" in w for w in warnings)


def test_empty_prompt_is_an_error():
    with pytest.raises(ValueError, match="Prompt is empty"):
        g.generate(client_with(FakeTransport()), IMAGEX, "  ", SETTINGS, [])


def test_no_credits_error_reaches_the_node():
    with pytest.raises(NoCreditsError):
        g.generate(client_with(FakeTransport(script=[402])), IMAGEX, "p", SETTINGS, [])


def test_find_model_from_cache_then_refresh(user_dir):
    model_list.save_cache([IMAGEX], user_dir / "image_models_cache.json")
    fake = FakeTransport()
    assert g.find_model("fake/imagex-1", client_with(fake))["id"] == "fake/imagex-1"
    assert fake.calls == []  # found in cache, no fetch
    assert g.find_model("fake/text-only", client_with(fake))["id"] == "fake/text-only"
    assert len(fake.calls) == 1  # not in cache -> one refresh
    with pytest.raises(ValueError, match="not in the image model list .2 models.. Press .refresh models."):
        g.find_model("nope/none", client_with(fake))


def test_label_with_star_maps_to_id():
    assert model_list.id_from_label("★ fake / imagex-1") == "fake/imagex-1"


def test_run_without_key_is_a_clear_error(user_dir):
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        g.OpenRouterGenerate().run("p", "fake / imagex-1", "auto", "auto", "auto", 0, "")


def test_info_text():
    text = g.info_text({"model": "a/b", "cost_usd": 0.039, "seed": 7,
                        "params_sent": ["seed"], "refs_sent": 1})
    assert "model: a/b" in text and "cost: $0.0390" in text and "seed: 7" in text
    assert "cost: unknown" in g.info_text({"model": "a/b", "cost_usd": None, "seed": 0,
                                           "params_sent": [], "refs_sent": 0})
