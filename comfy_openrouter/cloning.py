"""Voice cloning for the Speak node: reference clips -> ``input_references``.

OpenRouter format (TTS guide): 1-3 ``{"type": "input_audio", "input_audio": {"data":
"data:audio/wav;base64,..."}}`` items, each optionally followed by its transcript
``{"type": "text", "text": ...}``; max 15 MiB decoded per clip, transcript max 10,000
characters. The model list has no cloning flag, so ``NOTES`` holds the models the
OpenRouter docs name as supporting it (provider-specific, may change).
"""

import base64
import hashlib
import io
import wave

MAX_CLIPS = 3
MAX_CLIP_BYTES = 15 * 1024 * 1024
MAX_TRANSCRIPT = 10_000
# id substring -> note shown on the Speak node (from OpenRouter's TTS guide).
NOTES = {
    "seed-audio": "Voice cloning: yes · up to 3 clips; refer to them as @Audio1… in the "
                  "text; voice is left empty; transcript ignored",
    "fish-audio/": "Voice cloning: yes · 1 clip + transcript recommended (not with S1)",
    "heygen-voice": "Voice cloning: yes · 1 WAV/MP3 clip (first 3 min used); format pcm",
    "voxtral": "Voice cloning: yes · zero-shot from a short clip",
}
UNKNOWN = "Voice cloning: not listed for this model (a sample may be rejected)"


def note(model_id):
    for key, text in NOTES.items():
        if key in (model_id or ""):
            return text
    # Naming the model makes it visible which model the server was asked about.
    return f"{UNKNOWN} ({model_id or 'no model'})"


def wav_from_pcm16(pcm, channels, rate):
    """Interleaved 16-bit PCM bytes -> WAV file bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def audio_to_wavs(audio):
    """ComfyUI AUDIO dict -> list of WAV bytes, one per batch item (max 3)."""
    import numpy as np

    waveform, rate = audio["waveform"], int(audio["sample_rate"])
    arr = waveform.detach().cpu().numpy() if hasattr(waveform, "detach") else np.asarray(waveform)
    if arr.ndim == 2:  # [channels, samples] without batch
        arr = arr[None]
    out = []
    for item in arr[:MAX_CLIPS]:  # item: [channels, samples]
        pcm = (np.clip(item, -1.0, 1.0) * 32767).astype("<i2").T.tobytes()
        out.append(wav_from_pcm16(pcm, item.shape[0], rate))
    return out


def references(clips, transcript=""):
    """``input_references`` list and recipe refs for WAV clips. The transcript belongs to
    the first clip (it must directly follow its clip)."""
    if len(clips) > MAX_CLIPS:
        raise ValueError(f"At most {MAX_CLIPS} voice samples, got {len(clips)}")
    transcript = (transcript or "").strip()
    if len(transcript) > MAX_TRANSCRIPT:
        raise ValueError(f"Sample transcript is longer than {MAX_TRANSCRIPT} characters")
    parts, refs = [], []
    for i, clip in enumerate(clips):
        if len(clip) > MAX_CLIP_BYTES:
            raise ValueError(f"Voice sample {i + 1} is larger than 15 MB: use a shorter clip")
        data = "data:audio/wav;base64," + base64.b64encode(clip).decode("ascii")
        parts.append({"type": "input_audio", "input_audio": {"data": data}})
        if i == 0 and transcript:
            parts.append({"type": "text", "text": transcript})
        with wave.open(io.BytesIO(clip)) as w:
            seconds = round(w.getnframes() / w.getframerate(), 2)
        refs.append({"audio_hash": "sha256:" + hashlib.sha256(clip).hexdigest(),
                     "seconds": seconds})
    return parts, refs
