#!/usr/bin/env python3
"""Render frames from a .dur file to a PNG contact sheet.

This is a development/preview helper, not part of the Durdraw format.  It uses
Pillow and a monospace TTF font so we can eyeball colors and composition
without launching a terminal UI.

Usage:
    python3 preview_dur.py anubis-256-160x50.dur preview.png
    python3 preview_dur.py anubis-256-160x50.dur preview.png --frames 1,23,45,67
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# xterm / Durdraw 256-color palette for the first 16 entries.
BASE16 = [
    (0, 0, 0),        # 0 black
    (0, 0, 170),      # 1 blue
    (0, 170, 0),      # 2 green
    (0, 170, 170),    # 3 cyan
    (170, 0, 0),      # 4 red
    (170, 0, 170),    # 5 magenta
    (170, 85, 0),     # 6 yellow/brown
    (170, 170, 170),  # 7 white
    (85, 85, 85),     # 8 gray
    (85, 85, 255),    # 9 bright blue
    (85, 255, 85),    # 10 bright green
    (85, 255, 255),   # 11 bright cyan
    (255, 85, 85),    # 12 bright red
    (255, 85, 255),   # 13 bright magenta
    (255, 255, 85),   # 14 bright yellow
    (255, 255, 255),  # 15 bright white
]


def xterm256(index: int) -> tuple[int, int, int]:
    if index < 16:
        return BASE16[index]
    if index < 232:
        n = index - 16
        r = n // 36
        g = (n % 36) // 6
        b = n % 6
        levels = [0, 95, 135, 175, 215, 255]
        return levels[r], levels[g], levels[b]
    v = 8 + (index - 232) * 10
    return v, v, v


def durdraw16(index: int) -> tuple[int, int, int]:
    # Durdraw 16-color foreground indices: 1=black, 2=blue, ... 16=bright white.
    if index <= 0:
        return (0, 0, 0)
    return BASE16[(index - 1) % 16]


def load_dur(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))["DurMovie"]


def render_frame(
    movie: dict,
    frame_index: int,
    font: ImageFont.FreeTypeFont,
    cell_w: int,
    cell_h: int,
    scale: int,
) -> Image.Image:
    width = movie["sizeX"]
    height = movie["sizeY"]
    frame = movie["frames"][frame_index]
    color_format = movie["colorFormat"]
    palette = xterm256 if color_format == "256" else durdraw16

    image = Image.new("RGB", (width * cell_w, height * cell_h), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    for y in range(height):
        line = frame["contents"][y]
        for x in range(width):
            ch = line[x] if x < len(line) else " "
            fg, bg = frame["colorMap"][x][y]
            if bg:
                draw.rectangle(
                    [x * cell_w, y * cell_h, (x + 1) * cell_w - 1, (y + 1) * cell_h - 1],
                    fill=palette(bg),
                )
            if ch != " ":
                draw.text((x * cell_w, y * cell_h), ch, font=font, fill=palette(fg))

    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dur", type=Path, help="input .dur file")
    parser.add_argument("png", type=Path, help="output PNG path")
    parser.add_argument(
        "--frames",
        default="1,20,40,60",
        help="comma-separated 1-based frame numbers (default: 1,20,40,60)",
    )
    parser.add_argument("--font", default="/usr/share/fonts/TTF/DejaVuSansMono.ttf")
    parser.add_argument("--size", type=int, default=9, help="font size (default: 9)")
    parser.add_argument("--scale", type=int, default=2, help="integer upscale factor (default: 2)")
    parser.add_argument("--cols", type=int, default=2, help="contact-sheet columns (default: 2)")
    args = parser.parse_args()

    movie = load_dur(args.dur)
    width = movie["sizeX"]
    height = movie["sizeY"]

    font = ImageFont.truetype(args.font, args.size)
    # A monospace cell, with a little vertical breathing room.
    cell_w = max(1, int(round(font.getlength("M"))))
    bbox = font.getbbox("Ag")
    cell_h = max(1, int(round((bbox[3] - bbox[1]) * 1.18)))

    frame_numbers = [int(part) for part in args.frames.split(",") if part.strip()]
    images = [
        render_frame(movie, (num - 1) % len(movie["frames"]), font, cell_w, cell_h, args.scale)
        for num in frame_numbers
    ]

    label_h = 18 * args.scale
    cols = max(1, args.cols)
    rows = (len(images) + cols - 1) // cols
    sheet_w = cols * images[0].width
    sheet_h = rows * (images[0].height + label_h)
    sheet = Image.new("RGB", (sheet_w, sheet_h), (12, 12, 12))
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(args.font, 11 * args.scale)

    for i, image in enumerate(images):
        col = i % cols
        row = i // cols
        x = col * images[0].width
        y = row * (images[0].height + label_h)
        sheet.paste(image, (x, y))
        draw.text(
            (x + 4, y + images[0].height + 2),
            f"frame {frame_numbers[i]}  ({width}x{height}, {movie['colorFormat']} color)",
            font=label_font,
            fill=(170, 170, 170),
        )

    args.png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.png)
    print(f"wrote {args.png} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
