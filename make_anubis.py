#!/usr/bin/env python3
"""Generate a Durdraw .dur animation inspired by Anubis from Stargate SG-1.

The scene this is based on is "Full Circle" (SG-1 season 6 finale): Anubis
reveals to Daniel Jackson that he is only partially ascended.  Under the hood
there is no human face, just a shimmering event-horizon-like energy veil.

The output is a gzipped JSON ".dur" file using Durdraw file format 7, which is
what ly 1.4.x/1.5.x accepts.  Important format quirks handled here:

  * formatVersion must be 7 for ly.
  * contents is row-major: contents[y][x]
  * colorMap is column-major in v7: colorMap[x][y] = [fg, bg]
  * every contents line must be exactly `width` codepoints wide
  * ASCII-only glyphs, so Linux console fonts cannot turn characters into '#'
  * 256-color files use xterm palette indices >= 16.  ly's base-16 RGB table is
    in ANSI order, while Durdraw's base-16 indices are in xterm order; staying
    in the 6x6x6 cube / grayscale avoids that mismatch.
  * seamless loop: every time-dependent term completes an integer number of
    cycles over the frame count.

Usage:
    python3 make_anubis.py --colors 256
    python3 make_anubis.py --colors 16 --width 120 --height 44 --frames 90
    python3 make_anubis.py --width 240 --height 67 --frames 60 --fps 12

Then load it with Durdraw:
    durdraw anubis-256-160x50.dur
or preview it with:
    durview anubis-256-160x50.dur
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

# 256-color energy ramp: deep blue -> blue -> cyan -> white.
# All indices are >= 16, avoiding ly's differing base-16 ordering.
ENERGY_256 = (
    17, 18, 19, 20, 21, 26, 27, 32, 33, 38,
    39, 44, 45, 51, 87, 123, 159, 195, 231,
)

# Hood fabric: dark neutral grays, then cool blue as the face glow spills out.
HOOD_256 = (
    232, 232, 233, 233, 234, 234, 235, 235, 236, 236,
    237, 237, 238, 238, 239, 17, 18, 19, 20, 21, 27, 33, 39, 45,
)

# 16-color energy ramp (Durdraw 16-color indices; 1=black ... 16=bright white).
ENERGY_16 = (
    1, 1, 2, 2, 2, 2, 10, 10, 10,
    4, 4, 12, 12, 12, 16, 16, 16,
)

# 16-color hood ramp.
HOOD_16 = (
    1, 1, 1, 9, 9, 9, 8, 8,
    2, 2, 10, 10, 4, 4, 12,
)

HOOD_RAMP = " .:-=+*#"
FACE_RAMP = " .:-=+*#%@"

BAYER4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


# ---------------------------------------------------------------------------
# Geometry / shading helpers
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    """Static per-cell geometry and lighting, precomputed once."""

    in_face: bool
    in_hood: bool
    r: float          # superellipse radius in the face aperture (1 = edge)
    theta: float      # angle around the aperture
    u: float          # horizontal normalized face coordinate
    v: float          # vertical normalized face coordinate
    hood_base: float  # static fabric brightness
    feature: float    # static face-feature contribution (brow, nose, sockets...)
    eye: float        # eye-core contribution (0 outside the eye)
    dither: float     # ordered-dither offset


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 0.0 if x < edge0 else 1.0
    t = clamp01((x - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def gauss(dx: float, dy: float, sx: float, sy: float) -> float:
    return math.exp(-((dx / sx) ** 2 + (dy / sy) ** 2))


def superellipse(dx: float, dy: float, rx: float, ry: float, n: float = 1.65) -> float:
    return (abs(dx / rx) ** n + abs(dy / ry) ** n) ** (1.0 / n)


def hood_half_width(y: int, height: int, width: int) -> float:
    """Width of the cropped cowl silhouette at row y, in cells."""
    t = y / max(1, height - 1)
    hw = 0.28 + 0.40 * (t ** 0.70)
    hw += 0.20 * smoothstep(0.70, 1.0, t)  # shoulders flare out at the bottom
    return hw * width


def face_feature(u: float, v: float) -> tuple[float, float]:
    """Return (static feature contribution, eye-core contribution)."""
    feature = 0.0

    # The forehead recedes into the shadow of the cowl.
    feature -= 0.18 * gauss(u, v + 0.72, 0.90, 0.28)

    # Brow ridge: a dark shelf with a bright upper edge.
    feature -= 0.20 * math.exp(-(((v + 0.37) / 0.085) ** 2)) * math.exp(-((u / 0.62) ** 4))
    feature += 0.16 * math.exp(-(((v + 0.46) / 0.055) ** 2)) * math.exp(-((u / 0.60) ** 4))

    # Eye sockets (dark hollows around the glow).
    for ex in (-0.30, 0.30):
        feature -= 0.32 * gauss(u - ex, v + 0.17, 0.20, 0.15)

    # Cheekbones.
    for cx in (-0.52, 0.52):
        feature += 0.15 * gauss(u - cx, v - 0.14, 0.15, 0.20)

    # Nose bridge and its shadowed sides, ending in dark nostrils.
    feature += 0.22 * gauss(u, v - 0.02, 0.055, 0.28)
    for nx in (-0.11, 0.11):
        feature -= 0.12 * gauss(u - nx, v - 0.06, 0.060, 0.22)
    for nx in (-0.075, 0.075):
        feature -= 0.16 * gauss(u - nx, v - 0.28, 0.035, 0.045)

    # Mouth: a dark slit with a faint lower-lip catchlight.
    feature -= 0.30 * gauss(u, v - 0.47, 0.34, 0.070)
    feature += 0.14 * gauss(u, v - 0.55, 0.30, 0.045)

    # Chin / jaw catchlight.
    feature += 0.20 * gauss(u, v - 0.76, 0.40, 0.10)

    # Temple shadows.
    for tx in (-0.78, 0.78):
        feature -= 0.10 * gauss(u - tx, v + 0.05, 0.16, 0.32)

    # Eye cores: small, bright, and pulsing.
    eye = 0.0
    for ex in (-0.30, 0.30):
        eye += 1.70 * gauss(u - ex, v + 0.17, 0.080, 0.095)

    return feature, eye


def build_cells(width: int, height: int) -> list[Cell]:
    cx = width * 0.5
    cy = height * 0.45
    rx = width * 0.22
    ry = height * 0.36

    cells: list[Cell] = []
    for y in range(height):
        hw = hood_half_width(y, height, width)
        for x in range(width):
            dx = x - cx
            dy = y - cy
            v = dy / ry

            # The cowl opening is narrower at the top and widens toward the
            # cheeks, like a hood framing a face rather than a perfect oval.
            width_scale = 0.78 + 0.22 * clamp01((v + 1.0) * 0.5)
            u = dx / (rx * width_scale)
            r = (abs(u) ** 1.65 + abs(v) ** 1.65) ** (1.0 / 1.65)
            theta = math.atan2(v, u)
            in_face = r <= 1.0
            in_hood = (not in_face) and abs(dx) <= hw

            feature = 0.0
            eye = 0.0
            if in_face:
                feature, eye = face_feature(u, v)

            hood_base = 0.0
            if in_hood:
                d = max(0.0, r - 1.0)

                # Soft ambient fade away from the aperture.  Keep the fabric
                # dark; the glow at the face edge should be the bright part.
                hood_base = 0.12 + 0.12 * math.exp(-d / 0.60)

                # Cloth folds.
                fold1 = 0.5 + 0.5 * math.sin(theta * 11.0 + r * 2.2 + y * 0.10)
                fold2 = 0.5 + 0.5 * math.sin(x * 0.33 + y * 0.17)
                hood_base += 0.045 * fold1 + 0.030 * fold2

                # Radial folds radiating away from the face opening.
                for angle in (-1.18, -0.72, -0.28, 0.28, 0.72, 1.18, math.pi):
                    diff = math.atan2(math.sin(theta - angle), math.cos(theta - angle))
                    hood_base += 0.045 * math.exp(-((diff / 0.075) ** 2)) * math.exp(-d / 0.85)

                # Broad shoulder folds.
                if y > cy + ry * 0.35:
                    fold3 = 0.5 + 0.5 * math.sin((x - cx) * 0.16 + y * 0.34)
                    hood_base += 0.030 * fold3

                # A subtle center seam at the top of the cowl.
                if y < cy - ry * 0.2 and abs(dx) < 0.9:
                    hood_base += 0.025

                # Darken the outer silhouette so the hood melts into the screen.
                edge = smoothstep(0.0, 7.0, hw - abs(dx))
                hood_base *= 0.24 + 0.76 * edge

                # Faint rim light along the outer silhouette; it gives the
                # cropped cowl a readable edge against the black background.
                edge_light = math.exp(-(((hw - abs(dx) - 1.2) / 1.4) ** 2))
                hood_base += 0.060 * edge_light

                # Slightly darker at the very top and bottom.
                hood_base *= 0.60 + 0.40 * smoothstep(0.0, 5.0, y)
                hood_base *= 0.70 + 0.30 * smoothstep(0.0, 4.0, height - 1 - y)

            dither = (BAYER4[y & 3][x & 3] / 16.0 - 0.5) * 0.045

            cells.append(
                Cell(
                    in_face=in_face,
                    in_hood=in_hood,
                    r=r,
                    theta=theta,
                    u=u,
                    v=v,
                    hood_base=hood_base,
                    feature=feature,
                    eye=eye,
                    dither=dither,
                )
            )
    return cells


# ---------------------------------------------------------------------------
# Frame rendering
# ---------------------------------------------------------------------------

def pick(ramp, value: float):
    idx = int(value * (len(ramp) - 1) + 0.5)
    if idx < 0:
        idx = 0
    elif idx >= len(ramp):
        idx = len(ramp) - 1
    return ramp[idx]


def render_frame(
    cells: list[Cell],
    width: int,
    height: int,
    frame: int,
    frames: int,
    colors: str,
) -> tuple[list[str], list[list[list[int]]]]:
    """Render one frame as (contents rows, colorMap columns)."""
    tau = 2.0 * math.pi
    t = tau * frame / frames
    phase = frame / frames

    # Two periodic envelope shapes: a slow breath and a sharper reveal flare.
    pulse = 0.5 - 0.5 * math.cos(tau * phase)
    flare = math.exp(-(((phase - 0.58) / 0.055) ** 2))
    glow = 0.62 + 0.38 * pulse + 0.55 * flare
    veil = 0.80 + 0.20 * pulse

    energy_ramp = ENERGY_256 if colors == "256" else ENERGY_16
    hood_ramp = HOOD_256 if colors == "256" else HOOD_16

    rows: list[list[str]] = [[" "] * width for _ in range(height)]
    fg_rows: list[list[int]] = [[0] * width for _ in range(height)]

    for y in range(height):
        row = rows[y]
        fg_row = fg_rows[y]
        for x in range(width):
            cell = cells[y * width + x]

            if cell.in_face:
                r = cell.r
                th = cell.theta

                # Event-horizon ripples.  All temporal terms are integer
                # multiples of t, so the loop is seamless.
                wave1 = math.sin(9.0 * r - 2.0 * t + 1.8 * math.sin(3.0 * th + t))
                wave2 = math.sin(5.0 * th + 2.0 * t + 3.2 * r)
                wave3 = math.sin(4.0 * th + 3.5 * r - t)
                wave4 = math.sin(13.0 * r - t + 1.5 * math.sin(2.0 * th + t))

                value = 0.24 + 0.060 * wave1 + 0.040 * wave2 + 0.030 * wave3
                value += 0.020 * wave4

                # Concentric rings travelling through the veil.  The ring is
                # dimmer at the top of the opening, where the cowl shadows it.
                ring_mod = (0.68 + 0.32 * math.sin(5.0 * th + 2.0 * t))
                ring_mod *= 0.60 + 0.40 * smoothstep(-0.95, 0.55, cell.v)
                value += 0.50 * math.exp(-(((r - 0.89) / 0.075) ** 2)) * ring_mod * veil
                value += 0.18 * math.exp(-(((r - 0.64) / 0.065) ** 2)) * (0.68 + 0.32 * math.sin(5.0 * th + 2.0 * t))
                value += 0.11 * math.exp(-(((r - 0.41) / 0.060) ** 2)) * (0.68 + 0.32 * math.sin(5.0 * th + 2.0 * t))

                # Swirling center.
                value += 0.070 * math.sin(4.0 * th + 2.5 * r - t) * (1.0 - r)

                # Static face structure, gently breathing.
                value += cell.feature * (0.85 + 0.15 * pulse)

                # The eyes are the brightest part of the reveal.
                value += cell.eye * glow

                # Shadow under the brow of the cowl.
                value -= 0.12 * smoothstep(-0.35, -0.95, cell.v)

                # Darken the very edge of the aperture, so the bright ring
                # reads as the rim of the hood opening.
                value -= 0.30 * smoothstep(0.955, 1.0, r)

                value += cell.dither
                value = clamp01(value)

                char = pick(FACE_RAMP, value)
                color = pick(energy_ramp, value)

            elif cell.in_hood:
                # Light spilling from the face onto the cloth.
                spill = math.exp(-(((cell.r - 1.045) / 0.11) ** 2))
                spill *= 0.80 + 0.20 * math.cos(2.0 * cell.theta)
                base = cell.hood_base * (0.90 + 0.10 * pulse)
                base += spill * (0.42 * glow)
                base += 0.030 * math.exp(-(((cell.r - 1.0) / 0.55) ** 2)) * glow
                base += cell.dither * 0.7
                base = clamp01(base)

                char = pick(HOOD_RAMP, base)
                color = pick(hood_ramp, base)
            else:
                char = " "
                color = 0

            if char == " ":
                color = 0
            row[x] = char
            fg_row[x] = color

    contents = ["".join(row) for row in rows]

    # v7 colorMap is column-major: colorMap[x][y] = [fg, bg].
    color_map: list[list[list[int]]] = []
    for x in range(width):
        color_map.append([[fg_rows[y][x], 0] for y in range(height)])

    return contents, color_map


# ---------------------------------------------------------------------------
# .dur writing
# ---------------------------------------------------------------------------

def build_movie(
    width: int,
    height: int,
    frames: int,
    fps: float,
    colors: str,
    name: str,
    artist: str,
) -> dict:
    cells = build_cells(width, height)
    movie_frames = []
    for frame in range(frames):
        contents, color_map = render_frame(cells, width, height, frame, frames, colors)
        movie_frames.append(
            {
                "frameNumber": frame + 1,
                "delay": 0,
                "contents": contents,
                "colorMap": color_map,
            }
        )

    return {
        "DurMovie": {
            "formatVersion": 7,  # ly 1.4.x/1.5.x only accept version 7
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--width", type=int, default=160, help="canvas columns (default: 160)")
    parser.add_argument("--height", type=int, default=50, help="canvas rows (default: 50)")
    parser.add_argument("--frames", type=int, default=90, help="number of frames (default: 90)")
    parser.add_argument("--fps", type=float, default=15.0, help="frames per second (default: 15)")
    parser.add_argument("--colors", choices=("256", "16"), default="256", help="color format (default: 256)")
    parser.add_argument("--name", default="Anubis - Half-Ascended", help="artwork name metadata")
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

    movie = build_movie(
        width=args.width,
        height=args.height,
        frames=args.frames,
        fps=args.fps,
        colors=args.colors,
        name=args.name,
        artist=args.artist,
    )
    write_dur(movie, out)

    raw_size = len(json.dumps(movie, separators=(",", ":")).encode("utf-8"))
    print(
        f"wrote {out}  ({args.width}x{args.height}, {args.frames} frames, "
        f"{args.fps:g} fps, {args.colors} colors, {out.stat().st_size / 1024:.1f} KiB gzipped, "
        f"{raw_size / 1024 / 1024:.2f} MiB raw JSON)"
    )


if __name__ == "__main__":
    main()
