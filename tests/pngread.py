"""Minimal stdlib PNG reader for tests: text chunks and 8-bit non-interlaced pixels."""

import struct
import zlib

CHANNELS = {0: ("L", 1), 2: ("RGB", 3), 6: ("RGBA", 4)}


def chunks(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + body), f"bad CRC in {kind!r}"
        yield kind, body
        pos += 12 + length


def text(data):
    out = {}
    for kind, body in chunks(data):
        if kind == b"tEXt":
            key, _, value = body.partition(b"\x00")
            out[key.decode("latin-1")] = value.decode("latin-1")
    return out


def pixels(data):
    """Return ``(width, height, mode, raw)``; supports all five PNG row filters."""
    idat = b""
    for kind, body in chunks(data):
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and interlace == 0
            mode, bpp = CHANNELS[ctype]
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = width * bpp
    rows, prev, pos = [], bytearray(stride), 0
    for _ in range(height):
        ftype, line = raw[pos], bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 255
            elif ftype == 2:
                line[i] = (line[i] + b) & 255
            elif ftype == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, mode, b"".join(rows)
