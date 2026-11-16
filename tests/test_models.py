"""M1: model list cache, favorites, sort order, labels, offline start."""

import json

from comfy_openrouter import models as m
from comfy_openrouter.client import OpenRouterClient
from fakes import FAKE_MODELS, FakeTransport


def model(model_id, created=0, out=("image",)):
    return {"id": model_id, "created": created,
            "architecture": {"output_modalities": list(out)}}


def test_sort_family_then_favorites_then_newest():
    models = [
        model("openai/gpt-image-1", 300),
        model("google/old", 100),
        model("google/new", 500),
        model("google/fav-old", 50),
        model("Black-Forest-Labs/flux", 10),
    ]
    order = [x["id"] for x in m.sort_models(models, favorites=["google/fav-old"])]
    assert order == ["Black-Forest-Labs/flux", "google/fav-old", "google/new",
                     "google/old", "openai/gpt-image-1"]


def test_missing_created_sorts_last_within_family():
    models = [{"id": "a/x"}, model("a/y", 5)]
    assert [x["id"] for x in m.sort_models(models)] == ["a/y", "a/x"]


def test_only_image_output_models_kept():
    models = [model("a/img"), model("a/text", out=("text",)), {"no": "id"}]
    assert [x["id"] for x in m.image_models(models)] == ["a/img"]


def test_labels_and_round_trip():
    favs = ["google/gemini-3-pro-image"]
    assert m.label("google/gemini-3-pro-image", favs) == "★ google / gemini-3-pro-image"
    assert m.label("openai/gpt-image-1", favs) == "openai / gpt-image-1"
    for text in ["★ google / gemini-3-pro-image", "openai / gpt-image-1", "openai/gpt-image-1"]:
        assert m.id_from_label(text) in {"google/gemini-3-pro-image", "openai/gpt-image-1"}
    assert m.dropdown([model("b/x"), model("a/y")], ["b/x"]) == ["a / y", "★ b / x"]


def test_favorites_file_created_and_saved(tmp_path):
    path = tmp_path / "user" / "favorites.json"
    assert m.load_favorites(path) == []
    assert json.loads(path.read_text(encoding="utf-8")) == []
    m.save_favorites(["b/x", "a/y", "b/x"], path)
    assert m.load_favorites(path) == ["a/y", "b/x"]


def test_broken_files_do_not_crash(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert m.load_favorites(bad) == []
    assert m.load_cache(bad) == []


def test_first_fetch_writes_cache_then_offline_start_uses_it(tmp_path):
    cache = tmp_path / "models_cache.json"
    fake = FakeTransport()
    client = OpenRouterClient("k", transport=fake, sleep=lambda s: None)

    models, error = m.get_models(client, cache_path=cache)
    assert error is None and [x["id"] for x in models] == [x["id"] for x in FAKE_MODELS]
    assert cache.exists()

    # Offline start: no client (no key / no network) -> models come from the cache.
    models, error = m.get_models(None, cache_path=cache)
    assert error is None and len(models) == 2


def test_cache_used_without_refresh_and_fetch_on_refresh(tmp_path):
    cache = tmp_path / "models_cache.json"
    m.save_cache([model("old/one")], cache)
    fake = FakeTransport()
    client = OpenRouterClient("k", transport=fake, sleep=lambda s: None)

    models, _ = m.get_models(client, cache_path=cache)
    assert [x["id"] for x in models] == ["old/one"] and fake.calls == []

    models, _ = m.get_models(client, refresh=True, cache_path=cache)
    assert len(models) == 2 and len(fake.calls) == 1
    assert len(m.load_cache(cache)) == 2


def test_refresh_failure_falls_back_to_cache(tmp_path):
    cache = tmp_path / "models_cache.json"
    m.save_cache([model("old/one")], cache)

    def broken(method, url, headers, body, timeout):
        return 500, None

    client = OpenRouterClient("k", transport=broken, sleep=lambda s: None)
    models, error = m.get_models(client, refresh=True, cache_path=cache)
    assert [x["id"] for x in models] == ["old/one"]
    assert "using cache" in error


def test_no_cache_and_no_client_gives_empty_list(tmp_path):
    assert m.get_models(None, cache_path=tmp_path / "none.json") == ([], None)
