"""OpenRouter Video node: prompt (+ first/last frame) -> MP4, saved with a JSON recipe."""

import shutil
from pathlib import Path

from . import metadata
from . import models as model_list
from .client import OpenRouterError
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
    warnings = []
    listed = model_info.get("supported_frame_images")
    if frames and isinstance(listed, list) and listed:
        skipped = [kind for kind, _ in frames if kind not in listed]
        if skipped:
            warnings.append(f"not supported by {model_info['id']}, not sent: "
                            f"{', '.join(skipped)} (allowed: {listed})")
            frames = [f for f in frames if f[0] in listed]
    if not (prompt or "").strip() and not frames:
        raise ValueError("Prompt is empty (and no first/last frame the model accepts)")
    params = {
        "aspect_ratio": settings["aspect_ratio"],
        "resolution": settings["resolution"],
        "duration": settings["duration"] or None,  # 0 = model default
        "generate_audio": {"on": True, "off": False}.get(settings["generate_audio"]),
        "seed": settings["seed"],
    }
    params = {k: v for k, v in params.items() if v is not None and v != AUTO}
    dropped = []
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


OPTIONAL = ("aspect_ratio", "resolution", "duration", "generate_audio", "seed")
NO_PROVIDER_HINT = ("No provider could serve this request. Check that the model accepts a first or "
                    "last frame (only some do), that the aspect ratio, resolution and duration are "
                    "ones it lists, and that your account's privacy or region settings on "
                    "openrouter.ai allow its provider.")


def make_video(client, model_info, prompt, settings, frames, check_cancel=None):
    """Returns ``(mp4_bytes, info, warnings)``."""
    payload, info, warnings = video_payload(model_info, prompt, settings, frames)
    for text in warnings:  # logged before the request, so they also show when it fails
        log.warning("[OpenRouter] %s", text)
    try:
        data, cost = client.video(payload, check_cancel=check_cancel)
    except OpenRouterError as exc:
        if exc.status != 404 or "endpoint" not in str(exc).lower():
            raise
        extras = [k for k in OPTIONAL if k in payload]
        if not extras:
            raise OpenRouterError(f"{exc} {NO_PROVIDER_HINT}", status=exc.status) from exc
        # A 404 means no job was created, so nothing was charged: retry once with only the essentials.
        text = f"no provider took the request with {', '.join(extras)}; retrying without them"
        log.warning("[OpenRouter] %s", text)
        warnings.append(text)
        essentials = {k: v for k, v in payload.items() if k not in extras}
        try:
            data, cost = client.video(essentials, check_cancel=check_cancel)
        except OpenRouterError as second:
            if second.status != 404:
                raise
            raise OpenRouterError(f"{exc} It also failed with only the essentials (model, prompt"
                                  f"{', frames' if 'frame_images' in payload else ''}). "
                                  f"{NO_PROVIDER_HINT}", status=exc.status) from second
        info.update(params={}, params_sent=[], seed=None)  # what was really sent
    info["cost_usd"] = cost
    return data, info, warnings


def save_video(data, info, prompt, context, name, folder, pattern, node_id=None,
               prompt_id=None):
    meta = metadata.build(info, prompt, context, name, None, info["refs"], node_id=node_id,
                          prompt_id=prompt_id)
    return metadata.save_with_recipe(folder, pattern, file_fields(info, context, name), data,
                                     ".mp4", meta, "video")


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
        path = save_video(data, info, prompt, context, name, output_dir(folder),
                          load_settings()["filename_pattern"], unique_id, current_prompt_id())
        log.info("[OpenRouter] saved %s", path)
        ui = {**ui_payload(info, [path]), **preview_ui(path, comfy_temp_dir())}
        return {"ui": ui, "result": (str(path), info_text(info, [path]))}
