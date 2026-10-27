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
    RX, RY = W * 0.225, H * 0.355

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
    # Narrower at the brow, wider at the cheeks: a hood opening, not a circle.
    width_scale = 0.78 + 0.22 * np.clip((v + 1.0) * 0.5, 0.0, 1.0)
    u = (xx - CX) / (RX * width_scale)
    r = (np.abs(u) ** 2.0 + np.abs(v) ** 2.0) ** 0.5
    theta = np.arctan2(v, u)
    face = r <= 1.0

    # ---- hood -------------------------------------------------------------
    hood = _hood_mask(W, H)
    noise = _noise_field(W, H)

    fold = (
        0.50
        + 0.20 * np.sin(xx * 0.0062 + yy * 0.0130 + 2.0 * np.sin(xx * 0.0021 - yy * 0.0042))
        + 0.14 * np.sin(xx * 0.0142 - yy * 0.0044 + 1.5 * np.sin(yy * 0.0063))
        + 0.09 * np.sin(xx * 0.0310 + yy * 0.0210)
    )
    fold = np.clip(fold, 0.0, 1.0)

    d = np.maximum(0.0, r - 1.0)
    light = np.exp(-d / 0.60)

    # Fabric stays dark, but with enough contrast to read as a cowl.
    hood_val = 0.30 + 0.30 * light + 0.16 * fold + 0.08 * (noise - 0.5)
    hood_val = np.clip(hood_val, 0.0, 1.0)

    # Rim light along the opening, strongest where the energy spills out.
    rim = np.exp(-(((r - 1.05) / 0.055) ** 2))
    rim *= 0.62 + 0.38 * np.cos(2.0 * theta)
    hood_val += rim * (0.40 * glow)

    # Outer silhouette highlight.
    soft = np.asarray(
        Image.fromarray((hood * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)),
        dtype=np.float32,
    ) / 255.0
    edge = np.clip(hood - soft, 0.0, 1.0)
    hood_val += edge * 0.16

    # Cool blue-gray cloth.  B channel gets more, for the energy reflection.
    hood_rgb = np.stack(
        [hood_val * 62.0, hood_val * 72.0, hood_val * 92.0], axis=-1
    )
    hood_rgb += np.stack([rim * 10.0, rim * 62.0, rim * 128.0], axis=-1) * glow
    hood_rgb += np.stack([edge * 12.0, edge * 16.0, edge * 24.0], axis=-1)

    # ---- energy veil ------------------------------------------------------
    wave1 = np.sin(9.0 * r - 2.0 * t + 1.8 * np.sin(3.0 * theta + t))
    wave2 = np.sin(5.0 * theta + 2.0 * t + 3.2 * r)
    wave3 = np.sin(4.0 * theta + 3.5 * r - t)
    wave4 = np.sin(13.0 * r - t + 1.5 * np.sin(2.0 * theta + t))

    value = 0.30 + 0.075 * wave1 + 0.045 * wave2 + 0.035 * wave3 + 0.020 * wave4

    ring_mod = 0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    ring_mod *= 0.60 + 0.40 * _smoothstep(-0.95, 0.55, v)
    ring = np.exp(-(((r - 0.88) / 0.070) ** 2))
    value += 0.52 * ring * ring_mod * veil
    value += 0.18 * np.exp(-(((r - 0.63) / 0.060) ** 2)) * (
        0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    )
    value += 0.10 * np.exp(-(((r - 0.40) / 0.055) ** 2)) * (
        0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    )
    value += 0.07 * np.sin(4.0 * theta + 2.5 * r - t) * (1.0 - r)

    # Face structure.
    value -= 0.20 * _gauss(u, v + 0.70, 0.92, 0.30)          # brow shadow
    value -= 0.24 * np.exp(-(((v + 0.35) / 0.090) ** 2)) * np.exp(-((u / 0.64) ** 4))
    value += 0.17 * np.exp(-(((v + 0.46) / 0.060) ** 2)) * np.exp(-((u / 0.60) ** 4))

    for ex in (-0.30, 0.30):
        # Socket shadow and the bright eye itself.
        value -= 0.34 * _gauss(u - ex, v + 0.16, 0.20, 0.16)
        value += 1.70 * _gauss(u - ex, v + 0.16, 0.075, 0.105) * glow

    # Soft nose: a gentle ridge that fades out above the nostrils.
    value += 0.15 * _gauss(u, v - 0.02, 0.070, 0.26)
    for nx in (-0.085, 0.085):
        value -= 0.10 * _gauss(u - nx, v - 0.22, 0.050, 0.070)

    for cx in (-0.52, 0.52):
        value += 0.17 * _gauss(u - cx, v - 0.16, 0.15, 0.21)

    value -= 0.30 * _gauss(u, v - 0.48, 0.34, 0.075)         # mouth slit
    value += 0.14 * _gauss(u, v - 0.56, 0.30, 0.050)         # lower lip
    value += 0.20 * _gauss(u, v - 0.77, 0.40, 0.105)         # chin

    for tx in (-0.78, 0.78):
        value -= 0.10 * _gauss(u - tx, v + 0.05, 0.16, 0.32)

    # Inner rim shadow from the hood overhang.
    value -= 0.30 * _smoothstep(0.94, 1.0, r)
    value -= 0.14 * _smoothstep(-0.30, -0.95, v) * _smoothstep(0.70, 0.98, r)

    value = np.clip(value, 0.0, 1.0)

    # Deep blue -> cyan -> white.
    stops = [0.0, 0.16, 0.34, 0.52, 0.70, 0.86, 1.0]
    colors = np.array(
        [
            [2, 3, 12],
            [0, 9, 48],
            [0, 34, 132],
            [0, 92, 220],
            [0, 170, 250],
            [128, 232, 255],
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
