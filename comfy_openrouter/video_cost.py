"""Video model limits and a cost estimate for the Video node (shown before running).

OpenRouter's ``pricing_skus`` have no unit. Seen in practice: ByteDance Seedance is
priced per *video token*; ByteDance defines tokens = width x height x 24 fps x seconds
/ 1024. Check: 480p (854x480) -> 9607.5 tokens/s x $0.0000042 = $0.04035/s, exactly
OpenRouter's "from $0.04035/second". Other token-priced models: rule unknown, so no
estimate. Prices without "token" in the name are treated as per second (labelled).
"""

from . import models as model_list

FPS = 24
PIXELS = {"360p": 640 * 360, "480p": 854 * 480, "720p": 1280 * 720, "1080p": 1920 * 1080}
TOKEN_RULE_MODELS = ("seedance",)  # model ids whose token rule is known (see above)


def model_info(model, cache_path=None):
    """Cached model entry for a dropdown label or id (``{}`` if unknown)."""
    models, _ = model_list.get_models(None, cache_path=cache_path, kind="video")
    model_id = model_list.id_from_label(model or "")
    return model_list.find_model(models, model_id) or {"id": model_id}


def prices(info):
    out = {}
    for sku, value in (info.get("pricing_skus") or {}).items():
        try:
            out[sku] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def money(value):
    return f"${value:.4f}" if value < 1 else f"${value:.2f}"


def lengths_line(info):
    durs = sorted(d for d in info.get("supported_durations") or [] if isinstance(d, int))
    pos = [d for d in durs if d > 0]
    if not pos:
        text = "not listed"
    elif len(pos) > 2 and pos[-1] - pos[0] == len(pos) - 1:
        text = f"{pos[0]}–{pos[-1]} s"
    else:
        text = ", ".join(map(str, pos)) + " s"
    if -1 in durs:
        text += " (or auto)"
    res = ", ".join(info.get("supported_resolutions") or []) or "resolutions not listed"
    return f"Lengths: {text} · {res}", pos


def per_second(info, resolution, audio):
    """``({resolution: $/s}, note)`` or ``({}, reason)``."""
    p = prices(info)
    if not p:
        return {}, "Price: not listed for this model"
    token_skus = {k: v for k, v in p.items() if "token" in k}
    if token_skus:
        if not any(name in info.get("id", "") for name in TOKEN_RULE_MODELS):
            return {}, "Price: per video token (token rule unknown for this model)"
        sku = "video_tokens_without_audio" if audio == "off" else "video_tokens"
        price = token_skus.get(sku) or token_skus.get("video_tokens") or min(token_skus.values())
        listed = [r for r in info.get("supported_resolutions") or [] if r in PIXELS]
        targets = [resolution] if resolution in PIXELS else listed or list(PIXELS)
        rates = {r: PIXELS[r] * FPS / 1024 * price for r in targets}
        return rates, "per s (video tokens)"
    lo, hi = min(p.values()), max(p.values())
    # shortcut: unit unknown for non-token prices; assume per second like Seedance's page.
    return {"": lo, " ": hi} if lo != hi else {"": lo}, "per s (assumed unit)"


def info_lines(model, resolution="auto", duration=0, audio="auto", cache_path=None):
    """Lines the Video node shows, plus allowed durations for the duration widget."""
    info = model_info(model, cache_path)
    first, durations = lengths_line(info)
    lines = [first]
    rates, note = per_second(info, resolution, audio)
    if not rates:
        return {"lines": lines + [note], "durations": durations}
    named = [f"{money(v)} ({r})" for r, v in rates.items() if r.strip()]
    if named:
        lines.append("Price: " + ", ".join(named) + f" {note}")
    else:
        lo, hi = min(rates.values()), max(rates.values())
        rng = money(lo) if lo == hi else f"{money(lo)}–{money(hi)}"
        lines.append(f"Price: {rng} {note}")
    if duration and duration > 0:
        lo, hi = min(rates.values()) * duration, max(rates.values()) * duration
        rng = money(lo) if abs(hi - lo) < 1e-9 else f"{money(lo)}–{money(hi)}"
        lines.append(f"Estimate for {duration} s: ≈ {rng}")
    else:
        lines.append("Duration 0 = model default: set seconds for an estimate")
    return {"lines": lines, "durations": durations}
