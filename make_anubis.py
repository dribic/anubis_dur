#!/usr/bin/env python3
"""Generate a Durdraw .dur animation inspired by Anubis from Stargate SG-1.

The scene is from "Full Circle" (SG-1 season 6 finale): Anubis reveals to
Daniel Jackson that he is only partially ascended.  Under the hood there is no
human face, just a shimmering event-horizon-like energy veil.

The picture is rendered by ``anubis_scene.py`` at eight times the terminal
resolution (one cell = 8x16 pixels), then each cell is sampled to an ASCII
glyph and an ANSI color.  Rendering the source at high resolution and
downsampling gives much cleaner shapes than evaluating the scene per cell.

Output is a gzipped JSON ".dur" file using Durdraw file format 7, which is
what ly 1.4.x accepts.  Format quirks handled here:

  * formatVersion must be 7 for ly.
  * contents is row-major: contents[y][x]
  * colorMap is column-major in v7: colorMap[x][y] = [fg, bg]
  * every contents line must be exactly ``width`` codepoints wide
  * ASCII-only glyphs, so Linux console fonts cannot turn characters into '#'
  * 256-color files use xterm palette indices >= 16.  ly maps indices 0-15
    through an ANSI-ordered table, while Durdraw stores them in its own order,
    so staying in the 6x6x6 cube / grayscale avoids that mismatch.
  * seamless loop: every time-dependent term completes an integer number of
    cycles over the frame count.

Usage:
    python3 make_anubis.py --colors 256
    python3 make_anubis.py --colors 16 --width 120 --height 44 --frames 90
    python3 make_anubis.py --width 240 --height 67 --frames 60 --fps 12
    python3 make_anubis.py --shade mosaic

Then load it with Durdraw:
    durdraw anubis-256-160x50.dur
or preview it with:
    durview anubis-256-160x50.dur
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from anubis_scene import render_rgb


# Pixels per terminal cell in the high-resolution source.  This is the usual
# 8x16 console cell aspect, so the scene is never stretched.
CELL_W = 8
CELL_H = 16

# ASCII density ramp, darkest to brightest.  All printable ASCII on purpose.
RAMP = " .:-=+*#%@"

BAYER4 = np.array(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.float32,
) / 16.0 - 0.5

# Standard xterm 256-color palette.  ly implements exactly these levels:
# cube channels 0, 95, 135, 175, 215, 255 and grays 8..238 step 10.
_CUBE = np.array([0, 95, 135, 175, 215, 255], dtype=np.float32)


def _build_xterm() -> np.ndarray:
    colors = np.zeros((256, 3), dtype=np.float32)
    for index in range(16, 232):
        n = index - 16
        colors[index] = (_CUBE[n // 36], _CUBE[(n // 6) % 6], _CUBE[n % 6])
    for index in range(232, 256):
        value = 8 + (index - 232) * 10
        colors[index] = (value, value, value)
    return colors


# Durdraw 16-color foreground order (v7).  Index 0/1 are black; 2..16 are the
# colors an art file should use.  Values follow the classic ANSI palette.
DURDRAW16 = np.array(
    [
        (0, 0, 0),        # 0 black
        (0, 0, 0),        # 1 unused black
        (0, 0, 170),      # 2 blue
        (0, 170, 0),      # 3 green
        (0, 170, 170),    # 4 cyan
        (170, 0, 0),      # 5 red
        (170, 0, 170),    # 6 magenta
        (170, 85, 0),     # 7 yellow/brown
        (170, 170, 170),  # 8 light gray
        (85, 85, 85),     # 9 gray
        (85, 85, 255),    # 10 bright blue
        (85, 255, 85),    # 11 bright green
        (85, 255, 255),   # 12 bright cyan
        (255, 85, 85),    # 13 bright red
        (255, 85, 255),   # 14 bright magenta
        (255, 255, 85),   # 15 bright yellow
        (255, 255, 255),  # 16 bright white
    ],
    dtype=np.float32,
)

# RGB distance weights, slightly favouring green and blue detail.
_WEIGHTS = np.array([0.30, 0.45, 0.25], dtype=np.float32)


def _nearest(palette: np.ndarray, colors: np.ndarray) -> np.ndarray:
    """Index of the nearest palette entry for each RGB row in ``colors``."""
    flat = colors.reshape(-1, 3).astype(np.float32)
    delta = flat[:, None, :] - palette[None, :, :]
    distance = (delta * delta * _WEIGHTS).sum(axis=-1)
    return distance.argmin(axis=1)


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _sample(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Average the high-res render into one RGB triple per terminal cell."""
    height_px, width_px, _ = rgb.shape
    assert height_px == height * CELL_H and width_px == width * CELL_W
    blocks = rgb.reshape(height, CELL_H, width, CELL_W, 3)
    return blocks.mean(axis=(1, 3)).astype(np.float32)


def _palette_for(colors: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (palette RGB table, valid palette indices)."""
    if colors == "256":
        table = _build_xterm()
        indices = np.arange(16, 256)
        return table[indices], indices
    table = DURDRAW16
    indices = np.arange(2, 17)
    return table[indices], indices


def render_frame(
    rgb: np.ndarray,
    width: int,
    height: int,
    frame: int,
    colors: str,
    shade: str = "mosaic",
) -> tuple[list[str], list[list[list[int]]]]:
    """Turn one high-res RGB frame into (contents rows, colorMap columns)."""
    cell = _sample(rgb, width, height)
    luma = _luma(cell) / 255.0

    # Lift the midtones: the source is deliberately dark, but terminal
    # glyphs are sparse, so the veil needs a brighter curve to read.
    t = np.clip((luma - 0.008) / 0.42, 0.0, 1.0) ** 0.78

    # Keep hue, set brightness: dark blue stays blue but gains value, and
    # near-white highlights become white.
    peak = cell.max(axis=-1, keepdims=True)
    hue = cell / np.maximum(peak, 1.0)

    palette, indices = _palette_for(colors)

    # Ordered dithering breaks up the coarse ramp into a gradient.
    dither = np.tile(BAYER4, (height // 4 + 1, width // 4 + 1))[:height, :width]

    if colors == "16":
        # 16 colors cannot represent the soft blue-gray cowl: nearest-colour
        # mapping turns it into a flat gray slab.  Use classic ANSI art
        # instead: black background, glyph density for shading, and a short
        # blue -> cyan -> white foreground ramp.
        level = np.floor(t * (len(RAMP) - 1) + dither * 0.9 + 0.5).astype(np.int32)
        level = np.clip(level, 0, len(RAMP) - 1)
        lit = luma >= 0.012
        level[~lit] = 0

        ansi_ramp = np.array([2, 2, 2, 10, 10, 10, 12, 12, 16, 16], dtype=np.int64)
        ci = np.clip((t * (len(ansi_ramp) - 1) + 0.5).astype(np.int32), 0, len(ansi_ramp) - 1)
        fg = ansi_ramp[ci]
        fg[~lit] = 0
        bg = np.zeros((height, width), dtype=np.int64)
    elif shade == "mosaic":
        # Filled cells: background carries the smooth colour field, the
        # glyph adds a little texture on top.
        fg_rgb = hue * np.clip(t * 265.0, 0.0, 255.0)[..., None]
        bg_rgb = hue * np.clip(t ** 1.25 * 110.0, 0.0, 255.0)[..., None]
        fg = indices[_nearest(palette, fg_rgb)].reshape(height, width)
        bg = indices[_nearest(palette, bg_rgb)].reshape(height, width)

        glyph_t = np.clip((t - 0.22) / 0.78, 0.0, 1.0)
        level = np.floor(glyph_t * (len(RAMP) - 1) + dither * 0.8 + 0.5).astype(np.int32)
        level = np.clip(level, 0, len(RAMP) - 1)
        blank = luma < 0.006
        level[blank] = 0
        fg[blank] = 0
        bg[blank] = 0
    else:
        level = np.floor(t * (len(RAMP) - 1) + dither * 0.9 + 0.5).astype(np.int32)
        level = np.clip(level, 0, len(RAMP) - 1)
        lit = luma >= 0.006
        level[~lit] = 0
        fg = indices[_nearest(palette, cell)].reshape(height, width)
        fg[~lit] = 0
        bg = np.zeros((height, width), dtype=np.int64)

    glyphs = np.array(list(RAMP), dtype="<U1")[level]
    rows = ["".join(glyphs[y]) for y in range(height)]

    # v7 colorMap is column-major: colorMap[x][y] = [fg, bg].
    color_map: list[list[list[int]]] = []
    for x in range(width):
        color_map.append(
            [[int(fg[y, x]), int(bg[y, x])] for y in range(height)]
        )

    return rows, color_map


def build_movie(
    width: int,
    height: int,
    frames: int,
    fps: float,
    colors: str,
    name: str,
    artist: str,
    shade: str = "mosaic",
) -> dict:
    movie_frames = []
    for frame in range(frames):
        rgb = render_rgb(
            frame=frame,
            frames=frames,
            width=width * CELL_W,
            height=height * CELL_H,
        )
        contents, color_map = render_frame(rgb, width, height, frame, colors, shade)
        movie_frames.append(
            {
                "frameNumber": frame + 1,
                "delay": 0,
                "contents": contents,
                "colorMap": color_map,
            }
        )
        if (frame + 1) % 10 == 0 or frame + 1 == frames:
            print(f"  frame {frame + 1}/{frames}", flush=True)

    return {
        "DurMovie": {
            "formatVersion": 7,  # ly 1.4.x only accepts version 7
            "colorFormat": colors,
            "preferredFont": "fixed",
            "encoding": "utf-8",
            "name": name,
            "artist": artist,
            "framerate": float(fps),
            "sizeX": width,
            "sizeY": height,
            "extra": None,
            "frames": movie_frames,
        }
    }


def write_dur(movie: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(movie, separators=(",", ":"), ensure_ascii=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        handle.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--width", type=int, default=160, help="canvas columns (default: 160)")
    parser.add_argument("--height", type=int, default=50, help="canvas rows (default: 50)")
    parser.add_argument("--frames", type=int, default=90, help="number of frames (default: 90)")
    parser.add_argument("--fps", type=float, default=15.0, help="frames per second (default: 15)")
    parser.add_argument(
        "--colors", choices=("256", "16"), default="256", help="color format (default: 256)"
    )
    parser.add_argument(
        "--shade",
        choices=("mosaic", "glyph"),
        default="mosaic",
        help="mosaic fills cell backgrounds; glyph uses foreground characters only",
    )
    parser.add_argument(
        "--name", default="Anubis - Half-Ascended", help="artwork name metadata"
    )
    parser.add_argument("--artist", default="", help="artist metadata")
    parser.add_argument("--out", type=Path, default=None, help="output .dur path")
    args = parser.parse_args()

    if args.width < 20 or args.height < 10:
        parser.error("width must be >= 20 and height >= 10")
    if args.frames < 2:
        parser.error("frames must be >= 2")
    if args.fps <= 0:
        parser.error("fps must be > 0")

    out = args.out
    if out is None:
        out = Path(f"anubis-{args.colors}-{args.width}x{args.height}.dur")

    print(
        f"rendering {args.width}x{args.height}, {args.frames} frames, "
        f"{args.colors} colors..."
    )
    movie = build_movie(
        width=args.width,
        height=args.height,
        frames=args.frames,
        fps=args.fps,
        colors=args.colors,
        name=args.name,
        artist=args.artist,
        shade=args.shade,
    )
    write_dur(movie, out)

    raw_size = len(json.dumps(movie, separators=(",", ":")).encode("utf-8"))
    print(
        f"wrote {out}  ({args.width}x{args.height}, {args.frames} frames, "
        f"{args.fps:g} fps, {args.colors} colors, "
        f"{out.stat().st_size / 1024:.1f} KiB gzipped, "
        f"{raw_size / 1024 / 1024:.2f} MiB raw JSON)"
    )


if __name__ == "__main__":
    main()
