"""Video cost estimate shown on the Video node before running."""

import pytest

from comfy_openrouter import models as model_list
from comfy_openrouter import video_cost as vc

# As returned by OpenRouter for Seedance 2.0 Fast (seen in the owner's cache).
SEEDANCE = {"id": "bytedance/seedance-2.0-fast", "supported_durations": list(range(4, 16)),
            "supported_resolutions": ["480p", "720p"],
            "pricing_skus": {"video_tokens": "0.0000042",
                             "video_tokens_with_video_input": "0.000002475",
                             "video_tokens_without_audio": "0.0000042"}}


def test_seedance_rate_matches_openrouters_advertised_price():
    rates, note = vc.per_second(SEEDANCE, "480p", "auto")
    assert rates["480p"] == pytest.approx(0.04035, abs=1e-5)  # "from $0.04035/second"
    assert note == "per s (video tokens)"


def test_seedance_lines_with_duration(tmp_path):
    cache = tmp_path / "v.json"
    model_list.save_cache([SEEDANCE], cache)
    out = vc.info_lines("bytedance / seedance-2.0-fast", "720p", 4, "off", cache)
    assert out["durations"] == list(range(4, 16))
    assert out["lines"][0] == "Lengths: 4–15 s · 480p, 720p"
    assert out["lines"][1] == "Price: $0.0907 (720p) per s (video tokens)"
    assert out["lines"][2] == "Estimate for 4 s: ≈ $0.3629"


def test_auto_resolution_gives_a_range(tmp_path):
    cache = tmp_path / "v.json"
    model_list.save_cache([SEEDANCE], cache)
    out = vc.info_lines("bytedance / seedance-2.0-fast", "auto", 5, "auto", cache)
    assert out["lines"][1] == "Price: $0.0404 (480p), $0.0907 (720p) per s (video tokens)"
    assert out["lines"][2] == "Estimate for 5 s: ≈ $0.2018–$0.4536"


def test_duration_zero_asks_for_seconds(tmp_path):
    cache = tmp_path / "v.json"
    model_list.save_cache([SEEDANCE], cache)
    out = vc.info_lines("bytedance / seedance-2.0-fast", "480p", 0, "auto", cache)
    assert out["lines"][-1] == "Duration 0 = model default: set seconds for an estimate"


def test_unknown_token_rule_gives_no_estimate():
    model = {"id": "other/vid", "pricing_skus": {"video_tokens": "0.00001"}}
    rates, note = vc.per_second(model, "720p", "auto")
    assert rates == {} and "token rule unknown" in note


def test_plain_prices_are_labelled_as_assumed_per_second(tmp_path):
    cache = tmp_path / "v.json"
    model_list.save_cache([{"id": "x/vid", "pricing_skus": {"generate": "0.5"},
                            "supported_durations": [5, 10, -1]}], cache)
    out = vc.info_lines("x / vid", "auto", 10, "auto", cache)
    assert out["lines"] == ["Lengths: 5, 10 s (or auto) · resolutions not listed",
                            "Price: $0.5000 per s (assumed unit)",
                            "Estimate for 10 s: ≈ $5.00"]


def test_unknown_model_and_no_prices(tmp_path):
    out = vc.info_lines("nope / none", cache_path=tmp_path / "none.json")
    assert out["lines"] == ["Lengths: not listed · resolutions not listed",
                            "Price: not listed for this model"]
