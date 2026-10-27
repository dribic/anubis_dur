#!/usr/bin/env python3
"""Generate a .dur animation from a reference GIF of Anubis.

``anubis_glow.gif`` is a short loop of the "Full Circle" reveal: the black cowl
with the white energy face, shot in front of a wooden wall on the mothership.
For a display-manager background we only want the figure, so the orange wooden
background is keyed out to black before the frames are sampled to ASCII.

Background removal is deliberately simple and stable:

  * the wall is the only strongly orange part of the frame, so a hue test
    (R - B large) finds most of it;
  * the mask is computed once from the average frame, then applied to every
    frame, so the background never shimmers;
  * pixels close to the glowing face are protected, because the cowl has a
    warm brown trim around the eyes that must not be keyed out;
  * everything right of the wall is blanked as well, so the mothership wall
    cannot leak in at the edges.

The cleaned frames are cropped to the figure, scaled to preserve the console
cell aspect, centred on a black canvas, and then handed to the same sampler
used by ``make_anubis.py``.  Because the source is photographic, this variant
uses solid colour blocks rather than glyph shading: the glyph ramp only adds
noise on a soft, blown-out face.  It therefore requires the 256-colour format
(and ``full_color = true`` in ly); the 16-colour palette cannot represent it.

The GIF itself cuts back to its first frame, which would flash every three
seconds.  By default the clip is played forward and then backward, so the
energy flares, reveals the face, and settles again as a seamless loop.  Use
``--loop-mode cut`` for the original order.

Usage:
    python3 make_anubis_gif.py
    python3 make_anubis_gif.py --shade mosaic --loop-mode cut
    python3 make_anubis_gif.py --width 240 --height 67 --out anubis-gif-256-240x67.dur
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageSequence

import make_anubis as m


# Default crop around the figure, in source pixels (480x320).  The right edge
# is past the cowl so the wall can be keyed out without cutting the hood.
DEFAULT_CROP = (80, 0, 332, 320)


def load_gif(path: Path) -> tuple[list[np.ndarray], list[int]]:
    """Return composited RGB frames and their per-frame durations in ms."""
    image = Image.open(path)
    frames: list[np.ndarray] = []
    durations: list[int] = []
    for page in ImageSequence.Iterator(image):
        frames.append(np.asarray(page.convert("RGB"), dtype=np.float32))
        durations.append(int(page.info.get("duration", 0) or 0))
    return frames, durations


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary dilation with a square kernel, via Pillow's MaxFilter."""
    if radius <= 0:
        return mask
    image = Image.fromarray((mask * 255).astype(np.uint8))
    image = image.filter(ImageFilter.MaxFilter(radius * 2 + 1))
    return np.asarray(image) > 127


def _blur(mask: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return mask
    image = Image.fromarray((mask * 255).astype(np.uint8))
    image = image.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(image, dtype=np.float32) / 255.0


def background_mask(
    frames: list[np.ndarray],
    protect_glow: int = 18,
    right_edge: int = 320,
) -> np.ndarray:
    """Soft alpha of the background (mothership wall), 1 = remove."""
    average = np.mean(frames, axis=0)
    red, green, blue = average[..., 0], average[..., 1], average[..., 2]
    luma = red * 0.2126 + green * 0.7152 + blue * 0.0722

    # The wooden wall is the only strongly warm part of the plate.  The
    # threshold is deliberately sensitive: the wall goes almost black in the
    # slat gaps, but "warm and not black" still separates it from the
    # neutral cowl.
    wall = ((red - blue) > 14) & (red > 25) & (red >= green)
    wall = _dilate(wall, 5)

    # Keep the warm trim around the energy face: it is a costume detail, not
    # background, and it sits immediately next to the glow.
    glow = (luma > 130) & ((red - blue) < 15)
    glow = _dilate(glow, protect_glow)

    background = wall & ~glow
    background[:, right_edge:] = True
    return _blur(background, 2.0)


def clean_frames(
    frames: list[np.ndarray],
    background: np.ndarray,
    denoise: float = 1.0,
    sharpen: tuple[float, float] = (0.0, 0.0),
) -> list[np.ndarray]:
    """Key out the background, smooth dithering, and optionally sharpen.

    The GIF is heavily quantized, so a small blur removes palette noise
    before the unsharp pass; otherwise sharpening amplifies the dither into
    visible speckle.
    """
    alpha = 1.0 - background
    radius, amount = sharpen
    cleaned = []
    for frame in frames:
        keyed = frame * alpha[..., None]
        if denoise > 0:
            image = Image.fromarray(np.clip(keyed, 0, 255).astype(np.uint8))
            image = image.filter(ImageFilter.GaussianBlur(denoise))
            keyed = np.asarray(image, dtype=np.float32)
        if amount > 0 and radius > 0:
            # Sharpen luminance only: sharpening each channel separately
            # amplifies the GIF's chroma dither into red and green speckle
            # along the hood trim.
            luma = keyed @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            image = Image.fromarray(np.clip(luma, 0, 255).astype(np.uint8))
            blurred = np.asarray(
                image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32
            )
            keyed = np.clip(keyed + amount * (luma - blurred)[..., None], 0, 255)
        cleaned.append(keyed)
    return cleaned


def vignette_mask(
    width: int,
    height: int,
    rx: float = 0.25,
    ry: float = 0.54,
    inner: float = 0.78,
) -> np.ndarray:
    """Soft ellipse that fades the edges of the pasted portrait to black.

    The source has a lit wall behind the cowl on the left and a strip of
    mothership wall on the right; both are outside the figure and should not
    survive as a gray rectangle around it.
    """
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx = (xx - width * 0.5) / (width * rx)
    dy = (yy - height * 0.5) / (height * ry)
    distance = np.sqrt(dx * dx + dy * dy)
    t = np.clip((1.0 - distance) / (1.0 - inner), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def place_on_canvas(
    frame: np.ndarray,
    crop: tuple[int, int, int, int],
    width: int,
    height: int,
    subject_x: float,
    margin: float,
) -> np.ndarray:
    """Crop, scale with the console cell aspect, centre on black."""
    left, top, right, bottom = crop
    source = frame[top:bottom, left:right]
    src_h, src_w = source.shape[:2]

    canvas_w, canvas_h = width * m.CELL_W, height * m.CELL_H
    scale = canvas_h * (1.0 - 2.0 * margin) / src_h
    target_w = max(1, int(round(src_w * scale)))
    target_h = max(1, int(round(src_h * scale)))

    image = Image.fromarray(np.clip(source, 0, 255).astype(np.uint8))
    image = image.resize((target_w, target_h), Image.LANCZOS)

    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
    offset_x = int(round(canvas_w / 2 - (subject_x - left) * scale))
    offset_y = (canvas_h - target_h) // 2
    canvas.paste(image, (offset_x, offset_y))
    return np.asarray(canvas, dtype=np.float32)


def build_movie(
    gif: Path,
    width: int,
    height: int,
    colors: str,
    shade: str,
    tone: tuple[float, float, float],
    crop: tuple[int, int, int, int],
    margin: float,
    use_vignette: bool,
    sharpen: tuple[float, float],
    loop_mode: str,
    name: str,
    artist: str,
) -> dict:
    frames, durations = load_gif(gif)
    background = background_mask(frames, right_edge=crop[2])
    cleaned = clean_frames(frames, background, sharpen=sharpen)
    vignette = (
        vignette_mask(width * m.CELL_W, height * m.CELL_H) if use_vignette else None
    )

    average = np.mean(cleaned, axis=0)
    luma = average.mean(axis=2)
    ys, xs = np.nonzero(luma > 120)
    subject_x = float(xs.mean()) if xs.size else (crop[0] + crop[2]) / 2

    total_ms = sum(d for d in durations if d > 0) or len(frames) * 66
    fps = len(frames) * 1000.0 / total_ms

    # The GIF is a one-way reveal that cuts back to the start, which would
    # read as a hard flash every few seconds in a display-manager background.
    # Playing it forward and then backward turns it into a seamless pulse and
    # reads as the energy flaring and settling.
    if loop_mode == "pingpong":
        sequence = list(range(len(cleaned))) + list(range(len(cleaned) - 2, 0, -1))
    else:
        sequence = list(range(len(cleaned)))

    movie_frames = []
    for number, index in enumerate(sequence, start=1):
        frame = cleaned[index]
        canvas = place_on_canvas(frame, crop, width, height, subject_x, margin)
        if vignette is not None:
            canvas *= vignette[..., None]
        contents, color_map = m.render_frame(
            canvas, width, height, index, colors, shade, tone=tone
        )
        movie_frames.append(
            {
                "frameNumber": number,
                "delay": 0,
                "contents": contents,
                "colorMap": color_map,
            }
        )
        print(f"  frame {number}/{len(sequence)}", end="\r", flush=True)
    print(" " * 40, end="\r")

    print(
        f"  {len(sequence)} frames ({len(cleaned)} source, loop {loop_mode}), "
        f"{fps:.2f} fps, {total_ms} ms per direction, "
        f"figure centre x={subject_x:.0f}"
    )
    return {
        "DurMovie": {
            "formatVersion": 7,
            "colorFormat": colors,
            "preferredFont": "fixed",
            "encoding": "utf-8",
            "name": name,
            "artist": artist,
            "framerate": round(fps, 2),
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
    parser.add_argument("--gif", type=Path, default=Path("anubis_glow.gif"))
    parser.add_argument("--width", type=int, default=160, help="canvas columns (default: 160)")
    parser.add_argument("--height", type=int, default=50, help="canvas rows (default: 50)")
    parser.add_argument(
        "--shade",
        choices=("blocks", "mosaic", "glyph"),
        default="blocks",
        help="blocks fills whole cells (best for photos); mosaic adds glyph "
        "texture; glyph uses foreground characters only (default: blocks)",
    )
    parser.add_argument(
        "--tone",
        default="0.0,0.90,1.25",
        help="tone curve as offset,scale,gamma applied to luminance "
        "(default: 0.0,0.90,1.25)",
    )
    parser.add_argument(
        "--crop",
        default=",".join(str(v) for v in DEFAULT_CROP),
        help="crop as left,top,right,bottom in source pixels (default: 80,0,332,320)",
    )
    parser.add_argument(
        "--margin", type=float, default=0.02, help="fraction of canvas height left free (default: 0.02)"
    )
    parser.add_argument(
        "--sharpen",
        default="8,0.9",
        help="unsharp mask as radius,amount applied before sampling (default: 8,0.9)",
    )
    parser.add_argument(
        "--loop-mode",
        choices=("pingpong", "cut"),
        default="pingpong",
        help="pingpong plays the clip forward then backward for a seamless "
        "loop; cut keeps the source order (which jumps back to the first "
        "frame) (default: pingpong)",
    )
    parser.add_argument(
        "--no-vignette",
        action="store_true",
        help="do not fade the edges of the portrait into the black canvas",
    )
    parser.add_argument("--name", default="Anubis - Full Circle", help="artwork name metadata")
    parser.add_argument("--artist", default="", help="artist metadata")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.gif.exists():
        parser.error(f"gif not found: {args.gif}")
    if args.width < 20 or args.height < 10:
        parser.error("width must be >= 20 and height >= 10")
    if not (0.0 <= args.margin < 0.5):
        parser.error("margin must be in [0, 0.5)")

    crop = tuple(int(v) for v in args.crop.split(","))
    if len(crop) != 4:
        parser.error("--crop needs four values: left,top,right,bottom")
    try:
        tone = tuple(float(v) for v in args.tone.split(","))
    except ValueError:
        parser.error("--tone needs three numbers: offset,scale,gamma")
    if len(tone) != 3:
        parser.error("--tone needs three numbers: offset,scale,gamma")
    try:
        sharpen = tuple(float(v) for v in args.sharpen.split(","))
    except ValueError:
        parser.error("--sharpen needs two numbers: radius,amount")
    if len(sharpen) != 2:
        parser.error("--sharpen needs two numbers: radius,amount")

    out = args.out
    if out is None:
        out = Path(f"anubis-gif-256-{args.width}x{args.height}.dur")

    print(
        f"rendering {args.gif} -> {args.width}x{args.height}, "
        f"256 colors, shade {args.shade}..."
    )
    movie = build_movie(
        gif=args.gif,
        width=args.width,
        height=args.height,
        colors="256",
        shade=args.shade,
        tone=tone,
        crop=crop,
        margin=args.margin,
        use_vignette=not args.no_vignette,
        sharpen=sharpen,
        loop_mode=args.loop_mode,
        name=args.name,
        artist=args.artist,
    )
    write_dur(movie, out)

    raw_size = len(json.dumps(movie, separators=(",", ":")).encode("utf-8"))
    print(
        f"wrote {out}  ({args.width}x{args.height}, {len(movie['DurMovie']['frames'])} frames, "
        f"{movie['DurMovie']['framerate']:g} fps, 256 colors, "
        f"{out.stat().st_size / 1024:.1f} KiB gzipped, "
        f"{raw_size / 1024 / 1024:.2f} MiB raw JSON)"
    )


if __name__ == "__main__":
    main()
