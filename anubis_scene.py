#!/usr/bin/env python3
"""High-resolution Anubis scene renderer.

Renders the "Full Circle" look: a black cowl cropped by the frame, with a
shimmering event-horizon-like energy veil where the face should be, and two
white-hot eyes.  The result is an RGB numpy array which ``make_anubis.py``
samples down to terminal cells.

This module has no Durdraw dependencies, so it can also be run directly to
dump a PNG for inspection:

    python3 anubis_scene.py 0 scene.png
"""

from __future__ import annotations

import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


DEFAULT_W, DEFAULT_H = 1280, 800


def _smoothstep(a: float, b: float, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _gauss(x, y, sx, sy):
    return np.exp(-(((x / sx) ** 2) + ((y / sy) ** 2)))


def _hood_mask(width: int, height: int):
    """Silhouette of the cropped cowl, as a soft 0..1 mask."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    pts = [
        (width * 0.50, -height * 0.16),
        (width * 0.38, -height * 0.02),
        (width * 0.27, height * 0.04),
        (width * 0.18, height * 0.13),
        (width * 0.10, height * 0.28),
        (width * 0.045, height * 0.48),
        (width * 0.015, height * 0.72),
        (0, height),
        (width, height),
        (width * 0.985, height * 0.72),
        (width * 0.955, height * 0.48),
        (width * 0.90, height * 0.28),
        (width * 0.82, height * 0.13),
        (width * 0.73, height * 0.04),
        (width * 0.62, -height * 0.02),
    ]
    draw.polygon(pts, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2.5))
    return np.asarray(mask, dtype=np.float32) / 255.0


def _noise_field(width: int, height: int, seed: int = 7):
    rng = np.random.default_rng(seed)
    small = rng.standard_normal((96, 154)).astype(np.float32)
    small = (small - small.min()) / (small.max() - small.min())
    image = Image.fromarray((small * 255.0).astype(np.uint8)).resize(
        (width, height), Image.Resampling.BICUBIC
    )
    image = image.filter(ImageFilter.GaussianBlur(2))
    return np.asarray(image, dtype=np.float32) / 255.0


def render_rgb(
    frame: int = 0,
    frames: int = 90,
    width: int = DEFAULT_W,
    height: int = DEFAULT_H,
) -> np.ndarray:
    """Render one frame and return an (height, width, 3) uint8 RGB array."""
    W, H = width, height
    CX, CY = W * 0.5, H * 0.435
    RX, RY = W * 0.205, H * 0.355

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = 2.0 * math.pi * frame / frames
    phase = frame / frames

    # Slow breath plus a sharper "reveal" flare near 58% of the loop.
    pulse = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
    flare = math.exp(-(((phase - 0.58) / 0.055) ** 2))
    glow = 0.62 + 0.38 * pulse + 0.55 * flare
    veil = 0.82 + 0.18 * pulse

    # ---- aperture geometry ------------------------------------------------
    v = (yy - CY) / RY
    # Almond-shaped opening: narrow at the brow, wide at the cheeks, tapering
    # again at the chin.  A plain circle reads as a ghost head.
    width_scale = 0.58 + 0.42 * _smoothstep(-0.98, -0.05, v)
    width_scale *= 1.0 - 0.22 * _smoothstep(0.45, 1.0, v)
    u = (xx - CX) / (RX * width_scale)
    r = (np.abs(u) ** 2.0 + np.abs(v) ** 2.0) ** 0.5
    theta = np.arctan2(v, u)
    face = r <= 1.0

    # ---- hood -------------------------------------------------------------
    hood = _hood_mask(W, H)
    noise = _noise_field(W, H)

    # Cloth folds: mostly radial around the opening, plus a couple of broad
    # diagonal creases.  Kept low-contrast so the cowl stays near-black.
    fold = (
        0.50
        + 0.26 * np.sin(xx * 0.0052 + yy * 0.0118 + 2.2 * np.sin(xx * 0.0018 - yy * 0.0035))
        + 0.18 * np.sin(xx * 0.0118 - yy * 0.0040 + 1.8 * np.sin(yy * 0.0051))
        + 0.10 * np.sin(xx * 0.0260 + yy * 0.0180)
    )
    fold = np.clip(fold, 0.0, 1.0)

    d = np.maximum(0.0, r - 1.0)
    light = np.exp(-d / 0.42)

    # Fabric base.  The cowl is nearly black; only the area close to the
    # opening catches the energy, and the frame edges fall off to black.
    falloff = np.clip(
        1.0 - 0.62 * (((xx - CX) / (W * 0.52)) ** 2 + ((yy - CY) / (H * 0.60)) ** 2),
        0.0,
        1.0,
    )
    hood_val = 0.020 + 0.10 * light + 0.07 * fold * light + 0.008 * (noise - 0.5)
    hood_val *= 0.20 + 0.80 * falloff
    hood_val = np.clip(hood_val, 0.0, 1.0)

    # The cowl interior is almost black; a faint edge line keeps its cropped
    # silhouette readable against the black background.
    soft = np.asarray(
        Image.fromarray((hood * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7)),
        dtype=np.float32,
    ) / 255.0
    edge = np.clip(hood - soft, 0.0, 1.0)
    hood_val += edge * 0.42 * falloff

    # Rim light along the opening, irregular so it does not look like a bubble.
    # The top of the opening is in the shadow of the overhanging cowl.
    rim = np.exp(-(((r - 1.05) / 0.055) ** 2))
    rim *= 0.55 + 0.45 * np.cos(2.0 * theta) + 0.12 * np.sin(3.0 * theta + 0.7)
    rim *= 0.45 + 0.55 * _smoothstep(-0.90, 0.35, v)
    rim = np.clip(rim, 0.0, 1.2)
    hood_val += rim * (0.26 * glow)

    # Cool blue-gray cloth.  B channel gets more, for the energy reflection.
    hood_rgb = np.stack(
        [hood_val * 62.0, hood_val * 70.0, hood_val * 92.0], axis=-1
    )
    hood_rgb += np.stack([rim * 8.0, rim * 52.0, rim * 118.0], axis=-1) * glow

    # ---- energy veil ------------------------------------------------------
    wave1 = np.sin(9.0 * r - 2.0 * t + 1.8 * np.sin(3.0 * theta + t))
    wave2 = np.sin(5.0 * theta + 2.0 * t + 3.2 * r)
    wave3 = np.sin(4.0 * theta + 3.5 * r - t)
    wave4 = np.sin(13.0 * r - t + 1.5 * np.sin(2.0 * theta + t))

    value = 0.21 + 0.100 * wave1 + 0.060 * wave2 + 0.045 * wave3 + 0.025 * wave4

    ring_mod = 0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    ring_mod *= 0.60 + 0.40 * _smoothstep(-0.95, 0.55, v)
    ring = np.exp(-(((r - 0.90) / 0.060) ** 2))
    value += 0.45 * ring * ring_mod * veil
    value += 0.16 * np.exp(-(((r - 0.64) / 0.050) ** 2)) * (
        0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    )
    value += 0.08 * np.exp(-(((r - 0.40) / 0.045) ** 2)) * (
        0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    )
    value += 0.09 * np.sin(4.0 * theta + 2.5 * r - t) * (1.0 - r)

    # Thin bright filaments: the event-horizon texture of the veil.
    filament = np.exp(-((np.sin(6.0 * theta + 4.0 * r - 2.0 * t) / 0.22) ** 2))
    value += 0.10 * filament * (0.4 + 0.6 * r)

    # Face structure.  There is no flesh here, just an energy field shaped by
    # a remembered brow and two burning eyes.  No nose or mouth: those details
    # turn into a skull at terminal resolution.
    value -= 0.30 * _gauss(u, v + 0.68, 0.95, 0.30)          # brow shadow
    value -= 0.22 * np.exp(-(((v + 0.33) / 0.10) ** 2)) * np.exp(-((u / 0.68) ** 4))

    for ex in (-0.30, 0.30):
        # A soft socket shadow, then the eye itself: a narrow horizontal slit.
        value -= 0.24 * _gauss(u - ex, v + 0.15, 0.23, 0.19)
        value += 2.20 * _gauss(u - ex, v + 0.15, 0.110, 0.075) * glow

    # Shadow between the sockets, so the veil does not grow a bright nose.
    value -= 0.18 * _gauss(u, v + 0.03, 0.10, 0.20)

    # Faint cheek and jaw modelling.
    for cx in (-0.48, 0.48):
        value += 0.05 * _gauss(u - cx, v - 0.20, 0.16, 0.22)
    value -= 0.08 * _gauss(u, v - 0.60, 0.42, 0.16)

    for tx in (-0.78, 0.78):
        value -= 0.10 * _gauss(u - tx, v + 0.05, 0.16, 0.32)

    # Inner rim shadow from the hood overhang.
    value -= 0.30 * _smoothstep(0.93, 1.0, r)
    value -= 0.18 * _smoothstep(-0.25, -0.95, v) * _smoothstep(0.60, 0.96, r)

    value = np.clip(value, 0.0, 1.0)

    # Deep blue -> cyan -> pale shimmer -> white.
    stops = [0.0, 0.16, 0.34, 0.50, 0.66, 0.82, 1.0]
    colors = np.array(
        [
            [2, 4, 16],
            [0, 14, 62],
            [0, 46, 150],
            [0, 120, 225],
            [90, 200, 250],
            [190, 240, 255],
            [255, 255, 255],
        ],
        dtype=np.float32,
    )
    face_rgb = np.stack(
        [np.interp(value, stops, colors[:, i]) for i in range(3)], axis=-1
    )

    # Eye halo bleeding into the veil.
    halo = np.zeros_like(value)
    for ex in (-0.30, 0.30):
        halo += _gauss(u - ex, v + 0.16, 0.28, 0.26)
    face_rgb += np.stack([halo * 16.0, halo * 52.0, halo * 78.0], axis=-1) * glow

    face_rgb *= face[..., None]

    # ---- composite --------------------------------------------------------
    rgb = hood_rgb * hood[..., None]
    rgb = np.where(face[..., None], face_rgb, rgb)

    # Energy spilling onto the cloth around the opening.
    bleed = np.exp(-(((r - 1.06) / 0.11) ** 2)) * (~face)
    rgb += np.stack([bleed * 4.0, bleed * 30.0, bleed * 58.0], axis=-1) * glow

    # Vignette toward the frame edges.
    vx = (xx - W * 0.5) / (W * 0.5)
    vy = (yy - H * 0.5) / (H * 0.5)
    vig = np.clip(1.0 - 0.42 * (vx * vx + vy * vy), 0.0, 1.0)
    rgb *= vig[..., None]

    return np.clip(rgb, 0, 255).astype(np.uint8)


def render_png(frame: int = 0, frames: int = 90, path: str = "scene.png", width: int = DEFAULT_W, height: int = DEFAULT_H) -> None:
    Image.fromarray(render_rgb(frame, frames, width, height)).save(path)


def main() -> None:
    frame = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    out = sys.argv[2] if len(sys.argv) > 2 else "scene.png"
    render_png(frame, path=out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
