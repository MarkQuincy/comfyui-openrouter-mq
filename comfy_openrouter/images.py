"""Pixels, PNG files and ComfyUI IMAGE tensors.

A "pixels" value is a tuple ``(width, height, mode, raw)`` with 8-bit ``raw`` bytes,
mode ``"RGB"``, ``"RGBA"`` or ``"L"``. PNG writing and hashing are stdlib only.
numpy, Pillow and torch ship with ComfyUI; they are imported inside the functions
that need them, so the rest of the package (and the tests) work without them.

ComfyUI IMAGE = torch float tensor [batch, height, width, channels], values 0..1.
"""

import base64
import hashlib
import struct
import zlib

COLOR_TYPES = {"L": (0, 1), "RGB": (2, 3), "RGBA": (6, 4)}  # mode -> (PNG type, channels)


def pixel_hash(pixels):
    """``sha256:<hex>`` of ``"<width>x<height>:<mode>:"`` + raw pixel bytes."""
    width, height, mode, raw = pixels
    digest = hashlib.sha256(f"{width}x{height}:{mode}:".encode("ascii") + raw)
    return "sha256:" + digest.hexdigest()


def encode_png(pixels, text=None):
    """Pixels -> PNG bytes with optional ``tEXt`` chunks (``text`` values must be ASCII
    or Latin-1; pass JSON made with ``ensure_ascii=True``)."""
    width, height, mode, raw = pixels
    color_type, channels = COLOR_TYPES[mode]
    stride = width * channels
    if len(raw) != stride * height:
        raise ValueError("pixel data does not match width x height x channels")
    rows = b"".join(b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    out = [b"\x89PNG\r\n\x1a\n",
           chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))]
    for key, value in (text or {}).items():
        out.append(chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1")))
    out.append(chunk(b"IDAT", zlib.compress(rows, 6)))
    out.append(chunk(b"IEND", b""))
    return b"".join(out)


def data_url(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


# -- need numpy / Pillow / torch (present inside ComfyUI) ---------------------------


def tensor_to_pixels(image):
    """IMAGE tensor -> list of pixels tuples, one per batch item."""
    import numpy as np

    arr = image.detach().cpu().numpy() if hasattr(image, "detach") else np.asarray(image)
    if arr.ndim == 3:  # single image without batch dimension
        arr = arr[None]
    out = []
    for item in arr:
        u8 = np.clip(item * 255.0 + 0.5, 0, 255).astype(np.uint8)
        mode = {1: "L", 3: "RGB", 4: "RGBA"}[u8.shape[-1]]
        out.append((u8.shape[1], u8.shape[0], mode, np.ascontiguousarray(u8).tobytes()))
    return out


def decode_image(data):
    """Image file bytes (PNG/JPEG/WebP) -> RGB pixels tuple."""
    import io

    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return (img.width, img.height, "RGB", img.tobytes())


def pixels_to_tensor(items):
    """List of RGB pixels tuples -> IMAGE tensor [n, h, w, 3].

    Items of a different size than the first are skipped (a batch needs one size).
    Returns ``(tensor, skipped_count)``.
    """
    import numpy as np
    import torch

    first = items[0][:2]
    kept = [p for p in items if p[:2] == first]
    arrays = [np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3) for w, h, _, raw in kept]
    tensor = torch.from_numpy(np.stack(arrays).astype(np.float32) / 255.0)
    return tensor, len(items) - len(kept)
