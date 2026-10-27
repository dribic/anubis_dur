#!/usr/bin/env python3
"""Quick contact-sheet render of selected frames without generating the whole movie."""

import argparse
import json
from pathlib import Path

import make_anubis as m
from anubis_scene import render_rgb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=50)
    parser.add_argument("--colors", default="256")
    parser.add_argument("--shade", default="mosaic")
    parser.add_argument("--frames", default="0,23,52,69")
    parser.add_argument("--out", type=Path, default=Path("test.dur"))
    args = parser.parse_args()

    numbers = [int(x) for x in args.frames.split(",")]
    frames = []
    for i, number in enumerate(numbers, start=1):
        rgb = render_rgb(number, 90, args.width * m.CELL_W, args.height * m.CELL_H)
        contents, color_map = m.render_frame(
            rgb, args.width, args.height, number, args.colors, args.shade
        )
        frames.append({
            "frameNumber": i,
            "delay": 0,
            "contents": contents,
            "colorMap": color_map,
        })
    movie = {"DurMovie": {
        "formatVersion": 7,
        "colorFormat": args.colors,
        "preferredFont": "fixed",
        "encoding": "utf-8",
        "name": "test",
        "artist": "",
        "framerate": 15.0,
        "sizeX": args.width,
        "sizeY": args.height,
        "extra": None,
        "frames": frames,
    }}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(movie, fh)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
