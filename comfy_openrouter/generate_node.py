"""OpenRouter Generate node: prompt + refs + model -> IMAGE (one image per run).

``generate()`` holds the logic and works on PNG bytes, so it is testable without
torch. The node class only converts tensors and reads the environment.
Every run saves its image(s) with metadata, so no separate Save node is needed.
"""

import logging
import os
from datetime import date
from pathlib import Path

from . import metadata
from . import models as model_list
from .client import OpenRouterClient, max_refs
from .images import data_url, encode_png, pixel_hash
from .naming import load_settings
from .prompt_node import CATEGORY

log = logging.getLogger("comfyui-openrouter")

AUTO = "auto"
ASPECT_RATIOS = [AUTO, "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
RESOLUTIONS = [AUTO, "1K", "2K", "4K"]
QUALITIES = [AUTO, "low", "medium", "high"]
SEED_MAX = 2**31 - 1
NO_MODELS = "(no models - set OPENROUTER_API_KEY and restart ComfyUI)"


def make_client():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return OpenRouterClient(key) if key else None


def model_choices(client=None, kind="image"):
    """Dropdown labels. Fetches the list only if there is no cache yet."""
    models, error = model_list.get_models(client, kind=kind)
    if error:
        log.warning("[OpenRouter] %s", error)
    labels = model_list.dropdown(models, model_list.load_favorites())
    return labels or [NO_MODELS]


def find_model(model_id, client, kind="image"):
    """Model info from the cache; refreshes the cache once if the id is not there."""
    models, _ = model_list.get_models(None, kind=kind)
    info = model_list.find_model(models, model_id)
    if info is None and client is not None:
        models, error = model_list.get_models(client, refresh=True, kind=kind)
        if error:
            log.warning("[OpenRouter] %s", error)
        info = model_list.find_model(models, model_id)
    if info is None:
        raise ValueError(f"OpenRouter {kind} model {model_id!r} is not in the {kind} model "
                         f"list ({len(models)} models). Press 'refresh models', then pick a "
                         f"model from the dropdown.")
    return info


def generate(client, model_info, prompt, settings, ref_pixels):
    """Run one generation. ``settings``: aspect_ratio, resolution, quality, seed.
    ``ref_pixels``: list of pixels tuples (see ``images``).

    Returns ``(images, info, warnings)``; ``images`` are raw bytes from OpenRouter.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt is empty")
    warnings = []
    params = {k: (None if v == AUTO else v) for k, v in settings.items()}

    limit = max_refs(model_info)
    if len(ref_pixels) > limit:
        warnings.append(f"{len(ref_pixels)} reference images given, model "
                        f"{model_info['id']} accepts {limit}; extra ones not sent")
    sent_refs = ref_pixels[:limit]
    refs = [data_url(encode_png(p)) for p in sent_refs]

    result = client.generate(model_info, prompt, params=params, refs=refs)
    if result.params_dropped:
        warnings.append("not supported by %s, not sent: %s"
                        % (model_info["id"], ", ".join(result.params_dropped)))
    info = {
        "model": model_info["id"],
        "cost_usd": result.cost,
        "seed": settings.get("seed"),
        "params": {k: v for k, v in params.items() if v is not None},
        "params_sent": result.params_sent,
        "refs_sent": len(refs),
        "refs": [{"pixel_hash": pixel_hash(p), "width": p[0], "height": p[1]}
                 for p in sent_refs],
    }
    return result.images, info, warnings


def save_outputs(outputs, info, prompt, context, name, folder, pattern,
                 prompt_graph=None, extra_pnginfo=None, node_id=None, prompt_id=None):
    """Save each output (pixels tuple) as a new PNG with metadata. Returns paths."""
    fields = file_fields(info, context, name)
    paths = []
    for pixels in outputs:
        meta = metadata.build(info, prompt, context, name, pixel_hash(pixels), info["refs"],
                              node_id=node_id, prompt_id=prompt_id)
        data = encode_png(pixels, metadata.png_text(meta, prompt_graph, extra_pnginfo))
        paths.append(metadata.save_with_recipe(folder, pattern, fields, data, ".png", meta,
                                               "image"))
    return paths


def file_fields(info, context, name):
    """Values for the file name pattern."""
    return {
        "date": date.today().isoformat(),
        "project": (context or {}).get("project", ""),
        "person": (context or {}).get("person", ""),
        "name": name,
        "model": info["model"].split("/", 1)[-1],
    }


def output_dir(folder=""):
    """Where to save. ``folder`` from the node: empty = main folder, relative = a
    subfolder of the main folder, absolute (``D:\\...``) = used as is.
    Main folder: ``OPENROUTER_OUTPUT_DIR``, else ComfyUI output dir + ``openrouter``."""
    folder = (folder or "").strip().strip('"')
    if folder and Path(folder).is_absolute():
        return Path(folder)
    custom = os.environ.get("OPENROUTER_OUTPUT_DIR", "").strip()
    if custom:
        base = Path(custom)
    else:
        import folder_paths  # ComfyUI module

        base = Path(folder_paths.get_output_directory()) / "openrouter"
    return base / folder if folder else base


def current_prompt_id():
    try:
        from server import PromptServer  # ComfyUI module

        return PromptServer.instance.last_prompt_id
    except Exception:  # not inside ComfyUI, or attribute missing in this version
        return None


def ui_payload(info, paths):
    """Sent to the browser after a run; ``web/openrouter.js`` shows the cost."""
    return {"openrouter": [{"cost_usd": info["cost_usd"], "model": info["model"],
                            "files": [Path(p).name for p in paths]}]}


def info_text(info, paths=()):
    cost = info["cost_usd"]
    lines = [
        f"model: {info['model']}",
        "cost: " + ("unknown" if cost is None else f"${cost:.4f}"),
        f"seed: {info['seed']}",
        "sent: " + (", ".join(info["params_sent"]) or "-"),
        f"refs: {info['refs_sent']}",
    ]
    lines += [f"file: {Path(p).name}" for p in paths]
    return "\n".join(lines)


class OpenRouterGenerate:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"forceInput": True}),
                "model": (model_choices(make_client()),),
                "aspect_ratio": (ASPECT_RATIOS, {"default": AUTO}),
                "resolution": (RESOLUTIONS, {"default": AUTO}),
                "quality": (QUALITIES, {"default": AUTO}),
                "seed": ("INT", {"default": 0, "min": 0, "max": SEED_MAX,
                                 "control_after_generate": True}),
                "name": ("STRING", {"default": ""}),
            },
            "optional": {
                "context": ("OR_CONTEXT",),
                "ref_1": ("IMAGE",),
                "ref_2": ("IMAGE",),
                "ref_3": ("IMAGE",),
                "ref_4": ("IMAGE",),
                "folder": ("STRING", {"default": "", "tooltip":
                           "Empty: main output folder. A name like ProjectX\\portraits: "
                           "subfolder of it. A full path like D:\\Images: used as is."}),
            },
            "hidden": {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT",
                       "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    OUTPUT_NODE = True  # it saves files, so it runs even if nothing uses its outputs

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        # Accept labels not in the current dropdown (e.g. a saved "★ a / b" after
        # a/b was un-favorited); the model is checked against the list at run time.
        if model == NO_MODELS:
            return "No OpenRouter models available: set OPENROUTER_API_KEY and restart ComfyUI"
        return True

    def run(self, prompt, model, aspect_ratio, resolution, quality, seed, name,
            context=None, ref_1=None, ref_2=None, ref_3=None, ref_4=None, folder="",
            unique_id=None, prompt_graph=None, extra_pnginfo=None):
        from .images import decode_image, pixels_to_tensor, tensor_to_pixels

        client = make_client()
        if client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not set (set it and restart ComfyUI)")
        model_info = find_model(model_list.id_from_label(model), client)

        ref_pixels = []
        for ref in (ref_1, ref_2, ref_3, ref_4):
            if ref is not None:
                ref_pixels.extend(tensor_to_pixels(ref))  # a batch counts as several refs

        settings = {"aspect_ratio": aspect_ratio, "resolution": resolution,
                    "quality": quality, "seed": seed}
        images, info, warnings = generate(client, model_info, prompt, settings, ref_pixels)
        for text in warnings:
            log.warning("[OpenRouter] %s", text)

        outputs = [decode_image(raw) for raw in images]
        # Save first: the image is paid for, keep it even if a later step fails.
        pattern = load_settings()["filename_pattern"]
        paths = save_outputs(outputs, info, prompt, context, name, output_dir(folder), pattern,
                             prompt_graph, extra_pnginfo, unique_id, current_prompt_id())
        for path in paths:
            log.info("[OpenRouter] saved %s", path)

        tensor, skipped = pixels_to_tensor(outputs)
        if skipped:
            log.warning("[OpenRouter] %d image(s) of a different size were skipped", skipped)
        return {"ui": ui_payload(info, paths), "result": (tensor, info_text(info, paths))}
