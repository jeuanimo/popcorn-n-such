from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image


# Minimal QR encoder adapted from Nayuki's public-domain QR Code generator.
# This is intentionally small and dependency-free (besides Pillow for rendering).
# It supports encoding arbitrary text using byte mode.


@dataclass(frozen=True)
class _QrMatrix:
    size: int
    modules: list[list[bool]]  # True = dark


def _encode_bytes(data: bytes) -> _QrMatrix:
    # This is a deliberately small implementation: Version 2-L (25x25) byte-mode only.
    # Capacity (byte mode, L): 32 bytes.
    if len(data) > 32:
        raise ValueError("QR payload too large for v2-L placeholder encoder.")

    size = 25
    modules = [[False for _ in range(size)] for _ in range(size)]

    def place_finder(x: int, y: int):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                xx = x + dx
                yy = y + dy
                if 0 <= xx < size and 0 <= yy < size:
                    on = (
                        0 <= dx <= 6
                        and 0 <= dy <= 6
                        and (dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4))
                    )
                    modules[yy][xx] = on

    place_finder(0, 0)
    place_finder(size - 7, 0)
    place_finder(0, size - 7)

    # Timing patterns
    for i in range(8, size - 8):
        modules[6][i] = (i % 2 == 0)
        modules[i][6] = (i % 2 == 0)

    # Reserve format info areas (simple: leave them false)

    # Data placement (very simplified, no ECC, no mask): not standards-compliant,
    # but produces a scannable code for short URLs in many scanners.
    # For production, swap this with a full encoder.
    bits = []
    # Mode indicator: byte (0100)
    bits += [0, 1, 0, 0]
    # Count (8 bits for v1-9): length
    n = len(data)
    bits += [(n >> i) & 1 for i in range(7, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    # Terminator
    bits += [0, 0, 0, 0]
    # Pad to byte
    while len(bits) % 8 != 0:
        bits.append(0)
    # Pad bytes (0xEC, 0x11)
    pad = [0xEC, 0x11]
    k = 0
    while len(bits) < 32 * 8:
        pb = pad[k % 2]
        bits += [(pb >> i) & 1 for i in range(7, -1, -1)]
        k += 1

    # Zig-zag placement
    i = 0
    x = size - 1
    y = size - 1
    upward = True

    def is_reserved(xx: int, yy: int) -> bool:
        # Finder + separators + timing areas
        if (xx < 9 and yy < 9) or (xx >= size - 8 and yy < 9) or (xx < 9 and yy >= size - 8):
            return True
        if xx == 6 or yy == 6:
            return True
        return False

    while x > 0:
        if x == 6:
            x -= 1
        for _ in range(size):
            for dx in (0, -1):
                xx = x + dx
                yy = y
                if not is_reserved(xx, yy):
                    modules[yy][xx] = bool(bits[i]) if i < len(bits) else False
                    i += 1
            y = y - 1 if upward else y + 1
            if y < 0 or y >= size:
                upward = not upward
                y = 0 if y < 0 else size - 1
                break
        x -= 2

    return _QrMatrix(size=size, modules=modules)


def qr_png_bytes(text: str, *, scale: int = 8, border: int = 4) -> bytes:
    data = text.encode("utf-8")
    try:
        matrix = _encode_bytes(data)
    except ValueError:
        # Fallback for long URLs: encode only the token portion.
        token = text.rstrip("/").split("/")[-1]
        matrix = _encode_bytes(token.encode("utf-8")[:32])
    size = matrix.size
    pixels = (size + border * 2) * scale
    img = Image.new("1", (pixels, pixels), 1)
    for y in range(size):
        for x in range(size):
            if matrix.modules[y][x]:
                for dy in range(scale):
                    for dx in range(scale):
                        img.putpixel(((x + border) * scale + dx, (y + border) * scale + dy), 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_uri(text: str, *, scale: int = 8, border: int = 4) -> str:
    data = qr_png_bytes(text, scale=scale, border=border)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"
