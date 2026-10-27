#!/usr/bin/env python3
"""Validate a generated .dur file against the Durdraw v7 format and ly rules.

Checks structure, row widths, ASCII-only contents, colour indices, the
column-major colorMap, and the loop seam.  Also loads the file through
Durdraw's own parser to catch anything the format description misses.

Two loop checks are available:

  * ``--scene-loop`` re-renders the synthetic scene at frame 0 and frame N and
    requires them to match exactly.  This only applies to files produced by
    ``make_anubis.py``.
  * the default check reconstructs the first and last frames of the file and
    reports their mean colour difference, which catches a hard jump for any
    source (including the GIF-based file).

Usage:
    python3 validate_dur.py anubis-256-160x50.dur --scene-loop
    python3 validate_dur.py anubis-gif-256-160x50.dur
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import make_anubis as m
from anubis_scene import render_rgb


def load_movie(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))["DurMovie"]


def seam_difference(movie: dict) -> float:
    """Mean per-channel RGB difference between the last and first frame."""
    import numpy as np

    palette = (
        m._build_xterm() if movie["colorFormat"] == "256" else m.DURDRAW16
    )

    def cells(frame: dict) -> np.ndarray:
        indices = np.array(
            [[frame["colorMap"][x][y] for x in range(movie["sizeX"])]
             for y in range(movie["sizeY"])],
            dtype=np.int64,
        )
        return palette[indices]

    first = cells(movie["frames"][0])
    last = cells(movie["frames"][-1])
    return float(np.abs(first - last).mean())


def check(path: Path, scene_loop: bool = False) -> bool:
    movie = load_movie(path)
    ok = True

    def fail(message: str) -> None:
        nonlocal ok
        ok = False
        print(f"  FAIL: {message}")

    width = movie["sizeX"]
    height = movie["sizeY"]
    colors = movie["colorFormat"]
    frames = movie["frames"]

    print(f"file: {path}")
    print(f"  {width}x{height}, {colors} colors, {len(frames)} frames, "
          f"{movie['framerate']:g} fps, format v{movie['formatVersion']}")

    if movie["formatVersion"] != 7:
        fail("formatVersion must be 7 for ly 1.4.1")
    if colors not in ("16", "256"):
        fail("colorFormat must be '16' or '256'")
    if movie["encoding"] != "utf-8":
        fail("encoding must be utf-8 for ly")
    if width <= 0 or height <= 0:
        fail("invalid canvas dimensions")
    if movie["framerate"] <= 0:
        fail("framerate must be > 0")

    for number, frame in enumerate(frames, start=1):
        if frame["frameNumber"] != number:
            fail(f"frame {number}: frameNumber is {frame['frameNumber']}")
        if len(frame["contents"]) != height:
            fail(f"frame {number}: {len(frame['contents'])} rows, expected {height}")
        for y, line in enumerate(frame["contents"]):
            if len(line) != width:
                fail(f"frame {number} row {y}: {len(line)} codepoints, expected {width}")
            for ch in line:
                if not (32 <= ord(ch) <= 126):
                    fail(f"frame {number} row {y}: non-ASCII character {ch!r}")
                    break
        if len(frame["colorMap"]) != width:
            fail(f"frame {number}: colorMap has {len(frame['colorMap'])} columns, expected {width}")
        for x, column in enumerate(frame["colorMap"]):
            if len(column) != height:
                fail(f"frame {number} col {x}: {len(column)} entries, expected {height}")
            for y, pair in enumerate(column):
                if len(pair) != 2:
                    fail(f"frame {number} [{x}][{y}]: pair is {pair!r}")
                    continue
                fg, bg = pair
                if not isinstance(fg, int) or not isinstance(bg, int):
                    fail(f"frame {number} [{x}][{y}]: non-integer colour {pair!r}")
                    continue
                limit = 256 if colors == "256" else 17
                if not (0 <= fg < limit) or not (0 <= bg < limit):
                    fail(f"frame {number} [{x}][{y}]: colour out of range {pair!r}")
                if colors == "256" and (0 < fg < 16 or 0 < bg < 16):
                    fail(f"frame {number} [{x}][{y}]: base-16 index in 256-colour file {pair!r}")

    if scene_loop:
        # Seamless loop: frame `frames` is the same phase as frame 0.
        rgb0 = render_rgb(0, len(frames), width * m.CELL_W, height * m.CELL_H)
        rgbn = render_rgb(len(frames), len(frames), width * m.CELL_W, height * m.CELL_H)
        c0 = m.render_frame(rgb0, width, height, 0, colors, "mosaic")
        cn = m.render_frame(rgbn, width, height, len(frames), colors, "mosaic")
        if c0 != cn:
            fail("frame 0 and frame N differ: the animation is not a seamless loop")
        else:
            print("  loop: seamless (frame 0 == frame N)")

    # Colour distance across the actual loop seam.  Small values mean the
    # last frame flows into the first; a hard cut shows up as tens of levels.
    seam = seam_difference(movie)
    note = "ok" if seam < 12.0 else "visible jump"
    print(f"  loop seam: {seam:.1f} mean colour levels ({note})")

    # Load through Durdraw itself.
    try:
        from durdraw.durdraw_appstate import AppState
        from durdraw.durdraw_file import open_json_dur_file

        app_state = AppState()
        app_state.colorMode = colors
        app_state.charEncoding = "utf-8"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            loaded = open_json_dur_file(handle, app_state)
        if not loaded:
            fail("Durdraw open_json_dur_file() returned False")
        else:
            loaded_movie = loaded["mov"]
            got = (loaded["opts"].sizeX, loaded["opts"].sizeY, loaded_movie.frameCount)
            if got != (width, height, len(frames)):
                fail(f"Durdraw loaded {got}, expected {(width, height, len(frames))}")
            else:
                print("  Durdraw: loaded successfully "
                      f"({got[0]}x{got[1]}, {got[2]} frames)")
    except Exception as exc:  # noqa: BLE001 - validation should report, not crash
        fail(f"Durdraw load raised {type(exc).__name__}: {exc}")

    # Report a couple of content hashes for reproducibility.
    digest = hashlib.sha256(
        json.dumps(frames[0], sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    print(f"  first-frame hash: {digest}")

    return ok


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--scene-loop",
        action="store_true",
        help="also re-render frame 0 and frame N of the synthetic scene and compare",
    )
    args = parser.parse_args()

    success = True
    for path in args.files:
        success = check(path, scene_loop=args.scene_loop) and success
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
