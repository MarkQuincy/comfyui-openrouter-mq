"""OpenRouter Video node: prompt (+ first/last frame) -> MP4, saved with a JSON recipe."""

import shutil
from pathlib import Path

from . import metadata
from . import models as model_list
from .generate_node import (AUTO, NO_MODELS, SEED_MAX, current_prompt_id, file_fields,
                            find_model, info_text, log, make_client, model_choices,
                            output_dir, ui_payload)
from .images import data_url, encode_png, pixel_hash
from .naming import load_settings
from .prompt_node import CATEGORY

ASPECT_RATIOS = [AUTO, "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "9:21"]
RESOLUTIONS = [AUTO, "360p", "480p", "720p", "768p", "1080p", "1K", "2K", "4K"]
AUDIO_CHOICES = [AUTO, "on", "off"]
# param -> model field listing allowed values (GET /videos/models)
CHECKED = {"aspect_ratio": "supported_aspect_ratios", "resolution": "supported_resolutions",
           "duration": "supported_durations"}


def video_payload(model_info, prompt, settings, frames):
    """``settings``: aspect_ratio, resolution, duration, generate_audio, seed.
    ``frames``: list of ``(frame_type, pixels)``. Returns ``(payload, info, warnings)``."""
    if not (prompt or "").strip() and not frames:
        raise ValueError("Prompt is empty (and no first/last frame given)")
    params = {
        "aspect_ratio": settings["aspect_ratio"],
        "resolution": settings["resolution"],
        "duration": settings["duration"] or None,  # 0 = model default
        "generate_audio": {"on": True, "off": False}.get(settings["generate_audio"]),
        "seed": settings["seed"],
    }
    params = {k: v for k, v in params.items() if v is not None and v != AUTO}
    warnings, dropped = [], []
    for key, field in CHECKED.items():
        allowed = model_info.get(field)
        if key in params and isinstance(allowed, list) and allowed and params[key] not in allowed:
            dropped.append(f"{key}={params.pop(key)} (allowed: {allowed})")
    if dropped:
        warnings.append(f"not supported by {model_info['id']}, not sent: " + "; ".join(dropped))

    payload = {"model": model_info["id"], **params}
    if (prompt or "").strip():
        payload["prompt"] = prompt
    if frames:
        payload["frame_images"] = [
            {"type": "image_url", "image_url": {"url": data_url(encode_png(p))},
             "frame_type": kind} for kind, p in frames]
    info = {"model": model_info["id"], "cost_usd": None, "seed": params.get("seed"),
            "params": params, "params_sent": list(params), "refs_sent": len(frames),
            "refs": [{"pixel_hash": pixel_hash(p), "width": p[0], "height": p[1],
                      "frame_type": kind} for kind, p in frames]}
    return payload, info, warnings


def make_video(client, model_info, prompt, settings, frames, check_cancel=None):
    """Returns ``(mp4_bytes, info, warnings)``."""
    payload, info, warnings = video_payload(model_info, prompt, settings, frames)
    data, info["cost_usd"] = client.video(payload, check_cancel=check_cancel)
    return data, info, warnings


def save_video(data, info, prompt, context, name, folder, pattern, node_id=None,
               prompt_id=None):
    meta = metadata.build(info, prompt, context, name, None, info["refs"], node_id=node_id,
                          prompt_id=prompt_id)
    return metadata.save_with_recipe(folder, pattern, file_fields(info, context, name), data,
                                     ".mp4", meta, "video")


def model_info_payload(model, cache_path=None):
    """For the route: limits and prices of a video model from the cache (no network).
    ``prices`` are the ``pricing_skus`` values as numbers; OpenRouter gives no unit."""
    models, _ = model_list.get_models(None, cache_path=cache_path, kind="video")
    info = model_list.find_model(models, model_list.id_from_label(model or "")) or {}
    prices = {}
    for sku, value in (info.get("pricing_skus") or {}).items():
        try:
            prices[sku] = float(value)
        except (TypeError, ValueError):
            continue
    return {
        "durations": sorted(d for d in info.get("supported_durations") or []
                            if isinstance(d, int)),
        "resolutions": info.get("supported_resolutions") or [],
        "aspect_ratios": info.get("supported_aspect_ratios") or [],
        "prices": prices,
    }


def preview_ui(path, temp_dir):
    """Copy the saved video into ComfyUI's temp folder and describe it the way ComfyUI's
    own video nodes do, so the page shows it on the node. The saved file is untouched."""
    if temp_dir is None:
        return {}
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    name = f"openrouter_{path.name}"
    shutil.copyfile(path, temp_dir / name)
    return {"images": [{"filename": name, "subfolder": "", "type": "temp"}],
            "animated": [True]}


def comfy_temp_dir():
    try:
        import folder_paths  # ComfyUI module
    except ImportError:
        return None
    return folder_paths.get_temp_directory()


def comfy_cancel_check():
    """Raises when the user presses Cancel in ComfyUI (no-op outside ComfyUI)."""
    try:
        import comfy.model_management as mm  # ComfyUI module
    except ImportError:
        return None
    return mm.throw_exception_if_processing_interrupted


class OpenRouterVideo:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("file", "info")
    FUNCTION = "run"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"forceInput": True}),
                "model": (model_choices(make_client(), "video"),),
                "aspect_ratio": (ASPECT_RATIOS, {"default": AUTO}),
                "resolution": (RESOLUTIONS, {"default": AUTO}),
                "duration": ("INT", {"default": 0, "min": 0, "max": 60,
                                     "tooltip": "Seconds. 0 = model default."}),
                "generate_audio": (AUDIO_CHOICES, {"default": AUTO}),
                "seed": ("INT", {"default": 0, "min": 0, "max": SEED_MAX,
                                 "control_after_generate": True}),
                "name": ("STRING", {"default": ""}),
            },
            "optional": {
                "context": ("OR_CONTEXT",),
                "first_frame": ("IMAGE",),
                "last_frame": ("IMAGE",),
                "folder": ("STRING", {"default": ""}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        if model == NO_MODELS:
            return "No OpenRouter video models: set OPENROUTER_API_KEY, then refresh models"
        return True

    def run(self, prompt, model, aspect_ratio, resolution, duration, generate_audio, seed,
            name, context=None, first_frame=None, last_frame=None, folder="", unique_id=None):
        from .images import tensor_to_pixels

        client = make_client()
        if client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not set (set it and restart ComfyUI)")
        model_info = find_model(model_list.id_from_label(model), client, "video")
        frames = [(kind, tensor_to_pixels(img)[0])  # first image of a batch
                  for kind, img in (("first_frame", first_frame), ("last_frame", last_frame))
                  if img is not None]
        settings = {"aspect_ratio": aspect_ratio, "resolution": resolution,
                    "duration": duration, "generate_audio": generate_audio, "seed": seed}
        data, info, warnings = make_video(client, model_info, prompt, settings, frames,
                                          comfy_cancel_check())
        for text in warnings:
            log.warning("[OpenRouter] %s", text)
        path = save_video(data, info, prompt, context, name, output_dir(folder),
                          load_settings()["filename_pattern"], unique_id, current_prompt_id())
        log.info("[OpenRouter] saved %s", path)
        ui = {**ui_payload(info, [path]), **preview_ui(path, comfy_temp_dir())}
        return {"ui": ui, "result": (str(path), info_text(info, [path]))}
