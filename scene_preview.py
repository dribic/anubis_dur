#!/usr/bin/env python3
"""Prototype the high-resolution Anubis scene and save a PNG for inspection."""

from __future__ import annotations

import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1280, 800
CX, CY = W * 0.5, H * 0.45
RX, RY = W * 0.225, H * 0.36


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def gauss(x, y, sx, sy):
    return np.exp(-(((x / sx) ** 2) + ((y / sy) ** 2)))


def make_hood_mask():
    mask = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(mask)
    pts = [
        (W * 0.50, -H * 0.15),
        (W * 0.38, -H * 0.02),
        (W * 0.27, H * 0.04),
        (W * 0.18, H * 0.13),
        (W * 0.10, H * 0.28),
        (W * 0.05, H * 0.48),
        (W * 0.02, H * 0.72),
        (0, H),
        (W, H),
        (W * 0.98, H * 0.72),
        (W * 0.95, H * 0.48),
        (W * 0.90, H * 0.28),
        (W * 0.82, H * 0.13),
        (W * 0.73, H * 0.04),
        (W * 0.62, -H * 0.02),
    ]
    draw.polygon(pts, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2.5))
    return np.asarray(mask, dtype=np.float32) / 255.0


def make_scene(frame=0, frames=90):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = 2.0 * math.pi * frame / frames
    phase = frame / frames
    pulse = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
    flare = math.exp(-(((phase - 0.58) / 0.055) ** 2))
    glow = 0.62 + 0.38 * pulse + 0.55 * flare

    # ---- face aperture geometry -----------------------------------------
    v = (yy - CY) / RY
    width_scale = 0.78 + 0.22 * np.clip((v + 1.0) * 0.5, 0.0, 1.0)
    u = (xx - CX) / (RX * width_scale)
    r = (np.abs(u) ** 1.65 + np.abs(v) ** 1.65) ** (1.0 / 1.65)
    theta = np.arctan2(v, u)
    face = r <= 1.0

    # ---- static hood ----------------------------------------------------
    hood = make_hood_mask()

    # Organic cloth texture: low-frequency noise plus a few fold fields.
    rng = np.random.default_rng(7)
    noise = rng.standard_normal((120, 192)).astype(np.float32)
    noise = np.asarray(
        Image.fromarray(((noise - noise.min()) / (noise.max() - noise.min()) * 255).astype(np.uint8)).resize(
            (W, H), Image.Resampling.BICUBIC
        ),
        dtype=np.float32,
    ) / 255.0
    noise = np.asarray(
        Image.fromarray((noise * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),
        dtype=np.float32,
    ) / 255.0

    fold = (
        0.5
        + 0.22 * np.sin(xx * 0.006 + yy * 0.013 + 2.0 * np.sin(xx * 0.002 - yy * 0.004))
        + 0.16 * np.sin(xx * 0.014 - yy * 0.004 + 1.5 * np.sin(yy * 0.006))
        + 0.10 * np.sin(xx * 0.030 + yy * 0.021)
    )
    fold = np.clip(fold, 0.0, 1.0)

    d = np.maximum(0.0, r - 1.0)
    light = np.exp(-d / 0.55)
    hood_val = 0.10 + 0.16 * light + 0.07 * fold + 0.04 * noise

    # Rim light along the opening.
    rim = np.exp(-(((r - 1.045) / 0.060) ** 2))
    rim *= 0.65 + 0.35 * np.cos(2.0 * theta)
    hood_val += rim * (0.55 * glow)

    # Faint outer edge light from the silhouette boundary.
    soft = np.asarray(
        Image.fromarray((hood * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)),
        dtype=np.float32,
    ) / 255.0
    edge = np.clip(hood - soft, 0.0, 1.0)
    hood_val += edge * 0.30

    # Hood RGB: cool blue-gray.
    hood_rgb = np.stack(
        [
            hood_val * 26.0,
            hood_val * 31.0,
            hood_val * 42.0,
        ],
        axis=-1,
    )
    hood_rgb += np.stack([rim * 8.0, rim * 58.0, rim * 120.0], axis=-1) * glow
    hood_rgb += np.stack([edge * 14.0, edge * 18.0, edge * 26.0], axis=-1)

    # ---- energy veil ----------------------------------------------------
    wave1 = np.sin(9.0 * r - 2.0 * t + 1.8 * np.sin(3.0 * theta + t))
    wave2 = np.sin(5.0 * theta + 2.0 * t + 3.2 * r)
    wave3 = np.sin(4.0 * theta + 3.5 * r - t)
    wave4 = np.sin(13.0 * r - t + 1.5 * np.sin(2.0 * theta + t))

    value = 0.28 + 0.075 * wave1 + 0.045 * wave2 + 0.035 * wave3 + 0.020 * wave4

    ring_mod = 0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t)
    ring_mod *= 0.60 + 0.40 * smoothstep(-0.95, 0.55, v)
    value += 0.52 * np.exp(-(((r - 0.89) / 0.070) ** 2)) * ring_mod * (0.8 + 0.2 * pulse)
    value += 0.18 * np.exp(-(((r - 0.64) / 0.060) ** 2)) * (0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t))
    value += 0.10 * np.exp(-(((r - 0.41) / 0.055) ** 2)) * (0.68 + 0.32 * np.sin(5.0 * theta + 2.0 * t))

    # Face structure.
    value -= 0.18 * gauss(u, v + 0.72, 0.90, 0.28)  # forehead shadow
    value -= 0.26 * np.exp(-(((v + 0.37) / 0.085) ** 2)) * np.exp(-((u / 0.62) ** 4))
    value += 0.20 * np.exp(-(((v + 0.47) / 0.060) ** 2)) * np.exp(-((u / 0.60) ** 4))
    for ex in (-0.30, 0.30):
        value -= 0.36 * gauss(u - ex, v + 0.17, 0.20, 0.15)
        value += 1.75 * gauss(u - ex, v + 0.17, 0.080, 0.100) * glow
    value += 0.26 * gauss(u, v - 0.02, 0.060, 0.28)
    for nx in (-0.11, 0.11):
        value -= 0.13 * gauss(u - nx, v - 0.06, 0.060, 0.22)
    for nx in (-0.075, 0.075):
        value -= 0.18 * gauss(u - nx, v - 0.28, 0.040, 0.050)
    for cx in (-0.52, 0.52):
        value += 0.17 * gauss(u - cx, v - 0.14, 0.15, 0.20)
    value -= 0.32 * gauss(u, v - 0.47, 0.34, 0.070)
    value += 0.16 * gauss(u, v - 0.55, 0.30, 0.050)
    value += 0.22 * gauss(u, v - 0.76, 0.40, 0.100)
    for tx in (-0.78, 0.78):
        value -= 0.10 * gauss(u - tx, v + 0.05, 0.16, 0.32)

    # Dark inner rim / hood overhang shadow.
    value -= 0.34 * smoothstep(0.95, 1.0, r)
    value -= 0.16 * smoothstep(-0.30, -0.95, v) * smoothstep(0.7, 0.98, r)

    value = np.clip(value, 0.0, 1.0)

    # Smooth blue -> cyan -> white colormap.
    stops = [0.0, 0.18, 0.36, 0.55, 0.72, 0.86, 1.0]
    colors = np.array(
        [
            [2, 4, 14],
            [0, 10, 55],
            [0, 38, 145],
            [0, 95, 225],
            [0, 175, 255],
            [130, 235, 255],
            [255, 255, 255],
        ],
        dtype=np.float32,
    )
    face_rgb = np.stack(
        [np.interp(value, stops, colors[:, i]) for i in range(3)],
        axis=-1,
    )

    # Eye halo.
    halo = np.zeros_like(value)
    for ex in (-0.30, 0.30):
        halo += gauss(u - ex, v + 0.17, 0.26, 0.24)
    face_rgb += np.stack([halo * 18.0, halo * 55.0, halo * 80.0], axis=-1) * glow

    # Face pixels only inside the aperture.
    face_rgb *= face[..., None]

    # ---- composite ------------------------------------------------------
    rgb = hood_rgb * hood[..., None]
    rgb = np.where(face[..., None], face_rgb, rgb)

    # Blue glow bleeding onto the cloth just outside the opening.
    bleed = np.exp(-(((r - 1.05) / 0.12) ** 2)) * (~face)
    rgb += np.stack([bleed * 4.0, bleed * 28.0, bleed * 55.0], axis=-1) * glow

    # Vignette.
    vx = (xx - W * 0.5) / (W * 0.5)
    vy = (yy - H * 0.5) / (H * 0.5)
    vig = np.clip(1.0 - 0.38 * (vx * vx + vy * vy), 0.0, 1.0)
    rgb *= vig[..., None]

    return np.clip(rgb, 0, 255).astype(np.uint8)


def main():
    frame = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    out = sys.argv[2] if len(sys.argv) > 2 else "scene.png"
    Image.fromarray(make_scene(frame)).save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
