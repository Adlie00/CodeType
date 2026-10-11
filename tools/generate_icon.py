"""Generate the CODETYPE application icon.

Writes a multi-resolution Windows ``.ico`` plus a reference ``.png`` using only
the standard library, so the build has no extra dependency:

    python tools/generate_icon.py

Shapes are drawn at 4x and box-downsampled, which antialiases the diagonals
without needing an imaging library.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "images")
ICO_PATH = os.path.join(OUT_DIR, "icon.ico")
PNG_PATH = os.path.join(OUT_DIR, "icon.png")

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4

BACKGROUND = (10, 14, 24)
ACCENT = (0, 240, 255)
PROMPT = (0, 255, 170)
CURSOR = (255, 47, 208)
SHADOW = (4, 6, 12)

RGBA = tuple[int, int, int, int]


class Canvas:
    """A mutable RGBA pixel buffer with just enough drawing primitives."""

    def __init__(self, width: int, height: int, fill: RGBA) -> None:
        self.width = width
        self.height = height
        self.pixels = [[fill for _ in range(width)] for _ in range(height)]

    def blend(self, x: int, y: int, colour: RGBA) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        src_r, src_g, src_b, src_a = colour
        if src_a >= 255:
            self.pixels[y][x] = colour
            return
        dst_r, dst_g, dst_b, dst_a = self.pixels[y][x]
        alpha = src_a / 255.0
        inv = 1.0 - alpha
        self.pixels[y][x] = (
            int(src_r * alpha + dst_r * inv),
            int(src_g * alpha + dst_g * inv),
            int(src_b * alpha + dst_b * inv),
            max(dst_a, src_a),
        )

    def rect(self, x0: float, y0: float, x1: float, y1: float, colour: RGBA) -> None:
        for y in range(max(0, int(y0)), min(self.height, int(y1) + 1)):
            for x in range(max(0, int(x0)), min(self.width, int(x1) + 1)):
                self.blend(x, y, colour)

    def thick_segment(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        width: float,
        colour: RGBA,
    ) -> None:
        """A round-capped line, rasterised by stamping a disc along its path."""
        half = width / 2.0
        min_x = int(min(x0, x1) - half - 1)
        max_x = int(max(x0, x1) + half + 1)
        min_y = int(min(y0, y1) - half - 1)
        max_y = int(max(y0, y1) + half + 1)
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        for y in range(max(0, min_y), min(self.height, max_y + 1)):
            for x in range(max(0, min_x), min(self.width, max_x + 1)):
                px, py = x + 0.5 - x0, y + 0.5 - y0
                if length_sq <= 0.0:
                    distance_sq = px * px + py * py
                else:
                    t = max(0.0, min(1.0, (px * dx + py * dy) / length_sq))
                    ox, oy = px - t * dx, py - t * dy
                    distance_sq = ox * ox + oy * oy
                if distance_sq <= half * half:
                    self.blend(x, y, colour)

    def downsample(self, factor: int) -> "Canvas":
        out = Canvas(self.width // factor, self.height // factor, BACKGROUND + (255,))
        area = factor * factor
        for y in range(out.height):
            for x in range(out.width):
                r = g = b = a = 0
                for sy in range(factor):
                    row = self.pixels[y * factor + sy]
                    for sx in range(factor):
                        pr, pg, pb, pa = row[x * factor + sx]
                        r += pr
                        g += pg
                        b += pb
                        a += pa
                out.pixels[y][x] = (r // area, g // area, b // area, a // area)
        return out


def draw_icon(size: int) -> Canvas:
    """Draw the icon at ``size`` px square."""
    big = Canvas(size * SUPERSAMPLE, size * SUPERSAMPLE, BACKGROUND + (255,))
    s = size * SUPERSAMPLE
    unit = s / 256.0

    # Top status bar, echoing the in-game HUD strip.
    big.rect(0, 0, s, 26 * unit, ACCENT + (255,))
    big.rect(0, 26 * unit, s, 32 * unit, SHADOW + (255,))

    # Terminal prompt chevron.
    stroke = 30 * unit
    for offset, colour in ((5 * unit, SHADOW + (255,)), (0.0, PROMPT + (255,))):
        big.thick_segment(
            78 * unit + offset, 96 * unit + offset,
            132 * unit + offset, 150 * unit + offset,
            stroke, colour,
        )
        big.thick_segment(
            132 * unit + offset, 150 * unit + offset,
            78 * unit + offset, 204 * unit + offset,
            stroke, colour,
        )

    # Caret block the player is typing toward.
    big.rect(158 * unit, 176 * unit, 214 * unit, 206 * unit, SHADOW + (255,))
    big.rect(156 * unit, 174 * unit, 212 * unit, 204 * unit, CURSOR + (255,))

    # Underline tying the prompt and caret together.
    big.rect(0, 232 * unit, s, 240 * unit, ACCENT + (255,))

    return big.downsample(SUPERSAMPLE)


def canvas_to_bgra_dib(canvas: Canvas) -> bytes:
    """Pack a canvas as a 32-bit bottom-up DIB, as stored inside an .ico."""
    header = struct.pack(
        "<IiiHHIIiiII",
        40,                 # biSize
        canvas.width,       # biWidth
        canvas.height * 2,  # biHeight: XOR image + AND mask
        1,                  # biPlanes
        32,                 # biBitCount
        0,                  # biCompression (BI_RGB)
        0,                  # biSizeImage
        0, 0, 0, 0,         # ppm + colours
    )
    body = bytearray()
    for y in range(canvas.height - 1, -1, -1):  # bottom-up
        for x in range(canvas.width):
            r, g, b, a = canvas.pixels[y][x]
            body += bytes((b, g, r, a))
    # AND mask: fully opaque rows of zero bits, padded to 4 bytes per row.
    row_bytes = ((canvas.width + 31) // 32) * 4
    mask = bytes(row_bytes * canvas.height)
    return header + bytes(body) + mask


def write_png(path: str, canvas: Canvas) -> None:
    raw = bytearray()
    for row in canvas.pixels:
        raw.append(0)  # filter type: none
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


def write_ico(path: str, canvases: list[Canvas]) -> None:
    images = [canvas_to_bgra_dib(canvas) for canvas in canvases]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory = bytearray()
    for canvas, data in zip(canvases, images):
        directory += struct.pack(
            "<BBBBHHII",
            canvas.width if canvas.width < 256 else 0,  # 0 means 256
            canvas.height if canvas.height < 256 else 0,
            0,          # colour count
            0,          # reserved
            1,          # planes
            32,         # bit depth
            len(data),
            offset,
        )
        offset += len(data)
    with open(path, "wb") as handle:
        handle.write(header + bytes(directory) + b"".join(images))


def main() -> int:
    try:
        import game.constants  # noqa: F401
    except ImportError:
        sys.path.insert(0, ROOT)

    os.makedirs(OUT_DIR, exist_ok=True)
    canvases = [draw_icon(size) for size in SIZES]
    write_ico(ICO_PATH, canvases)
    write_png(PNG_PATH, canvases[-1])
    print(f"wrote {ICO_PATH} ({os.path.getsize(ICO_PATH)} bytes, sizes {SIZES})")
    print(f"wrote {PNG_PATH} ({os.path.getsize(PNG_PATH)} bytes, 256x256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
