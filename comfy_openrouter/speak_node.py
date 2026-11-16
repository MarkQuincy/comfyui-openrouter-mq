"""OpenRouter Speak node: text -> speech. Saves the audio + JSON recipe, outputs AUDIO."""

import io
import wave

from . import languages, metadata
from . import models as model_list
from .client import OpenRouterError
from .generate_node import (NO_MODELS, current_prompt_id, file_fields, find_model, info_text,
                            log, make_client, model_choices, output_dir, ui_payload)
from .naming import load_settings
from .prompt_node import CATEGORY

FORMATS = ["mp3", "pcm"]
# shortcut: the docs give no sample rate for pcm; 24 kHz 16-bit mono is what OpenAI and
# Gemini TTS return. Make it a widget if a model sounds too fast or too slow.
PCM_RATE = 24000


def speak(client, model_info, text, settings):
    """``settings``: voice, format, speed, instructions. Returns ``(audio_bytes, info)``."""
    if not text or not text.strip():
        raise ValueError("Text is empty")
    payload = {"model": model_info["id"], "input": text, "response_format": settings["format"]}
    if settings["voice"].strip():
        payload["voice"] = settings["voice"].strip()
    if settings["speed"] != 1.0:
        payload["speed"] = settings["speed"]
    if settings["instructions"].strip():
        payload["instructions"] = settings["instructions"].strip()
    try:
        audio = client.speech(payload)
    except OpenRouterError as exc:
        if "voice" not in payload and exc.status == 400 and "voice" in str(exc).lower():
            raise OpenRouterError(
                f"{exc}. {model_info['id']} has no default voice and OpenRouter lists no "
                f"voices for it: type a voice name from the model's page on openrouter.ai.",
                status=exc.status) from exc
        raise
    params = {k: v for k, v in payload.items() if k not in ("model", "input")}
    # shortcut: speech responses carry no cost; it would need GET /generation by id.
    info = {"model": model_info["id"], "cost_usd": None, "seed": None, "params": params,
            "params_sent": list(params), "refs_sent": 0, "refs": []}
    return audio, info


def pcm_to_wav(pcm, rate=PCM_RATE):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def save_speech(audio, fmt, info, text, context, name, folder, pattern,
                node_id=None, prompt_id=None):
    data, ext = (audio, ".mp3") if fmt == "mp3" else (pcm_to_wav(audio), ".wav")
    meta = metadata.build(info, text, context, name, None, [], node_id=node_id,
                          prompt_id=prompt_id)
    return metadata.save_with_recipe(folder, pattern, file_fields(info, context, name), data,
                                     ext, meta, "audio")


def to_comfy_audio(path):
    """Saved file -> ComfyUI AUDIO dict (needs torch/numpy, plus torchaudio for mp3)."""
    import torch

    if path.suffix == ".wav":
        import numpy as np

        with wave.open(str(path), "rb") as w:
            rate, frames = w.getframerate(), w.readframes(w.getnframes())
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        return {"waveform": torch.from_numpy(samples)[None, None], "sample_rate": rate}
    try:
        samples, rate = decode_with_av(path)  # PyAV ships with recent ComfyUI
        return {"waveform": torch.from_numpy(samples)[None], "sample_rate": rate}
    except Exception as av_exc:  # av missing or cannot read the file
        try:
            import torchaudio

            waveform, rate = torchaudio.load(str(path))
        except Exception as exc:  # torchaudio missing or no mp3 backend (torchcodec)
            raise RuntimeError(f"Saved {path.name}, but cannot load mp3 for the AUDIO output "
                               f"(PyAV: {av_exc}; torchaudio: {exc}). Use format 'pcm' "
                               f"instead.") from exc
    return {"waveform": waveform[None], "sample_rate": rate}


def decode_with_av(path):
    """Audio file -> (float32 array [channels, samples], sample_rate) via PyAV."""
    import av
    import numpy as np

    chunks, rate = [], None
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            rate = frame.sample_rate
            arr = frame.to_ndarray()
            if not frame.format.is_planar:  # packed: [1, samples * channels]
                arr = arr.reshape(-1, len(frame.layout.channels)).T
            if arr.dtype.kind == "i":
                arr = arr.astype(np.float32) / float(np.iinfo(arr.dtype).max + 1)
            chunks.append(arr.astype(np.float32))
    if not chunks:
        raise ValueError("no audio frames")
    return np.ascontiguousarray(np.concatenate(chunks, axis=1)), rate


class OpenRouterSpeak:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "info")
    FUNCTION = "run"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                # Only filters the model dropdown in the browser (web/openrouter.js).
                "language": (languages.choices(), {"default": languages.ALL_NAME}),
                "model": (model_choices(make_client(), "speech"),),
                "voice": ("STRING", {"default": "", "tooltip":
                          "Empty = the model's default voice. Names depend on the model; "
                          "a wrong name returns an error listing the valid voices."}),
                "format": (FORMATS, {"default": "mp3"}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.25, "max": 4.0, "step": 0.05}),
                "instructions": ("STRING", {"default": "", "multiline": True}),
                "name": ("STRING", {"default": ""}),
            },
            "optional": {
                "context": ("OR_CONTEXT",),
                "folder": ("STRING", {"default": ""}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        if model == NO_MODELS:
            return "No OpenRouter speech models: set OPENROUTER_API_KEY, then refresh models"
        return True

    def run(self, text, model, voice, format, speed, instructions, name, language=None,
            context=None,
            folder="", unique_id=None):
        client = make_client()
        if client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not set (set it and restart ComfyUI)")
        model_info = find_model(model_list.id_from_label(model), client, "speech")
        settings = {"voice": voice, "format": format, "speed": speed,
                    "instructions": instructions}
        audio, info = speak(client, model_info, text, settings)
        path = save_speech(audio, format, info, text, context, name, output_dir(folder),
                           load_settings()["filename_pattern"], unique_id, current_prompt_id())
        log.info("[OpenRouter] saved %s", path)
        return {"ui": ui_payload(info, [path]),
                "result": (to_comfy_audio(path), info_text(info, [path]))}
