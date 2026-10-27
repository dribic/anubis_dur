# Anubis — half-ascended `.dur` animation

A fan-made terminal animation for [Durdraw](https://github.com/cmang/durdraw), built as a
background for the [ly](https://github.com/fairyglade/ly) display manager.

The scene is Anubis from *Stargate SG-1* — specifically the "Full Circle" reveal, when he
shows Daniel Jackson that he is only partially ascended. Under the black cowl there is no
human face, just a shifting event-horizon of energy shaped into a vague skull.

The animation is a **6-second seamless loop**: a slow breathing pulse and a brighter flare
around the 3.5-second mark, then back to the resting glow.

![preview](preview-256.png)

## Files

| File | What it is |
| --- | --- |
| `anubis-256-160x50.dur` | 256-colour version, 160×50 cells, 90 frames, 15 fps. **Recommended default.** |
| `anubis-16-160x50.dur` | 16-colour fallback, same timing and size. |
| `anubis-256-240x67.dur` | Full-screen 256-colour version for a 1920×1080 console with an 8×16 font. Larger and heavier to load. |
| `make_anubis.py` | Generator: renders the scene and writes a `.dur` file. |
| `anubis_scene.py` | High-resolution scene renderer (numpy + Pillow). |
| `preview_dur.py` | Renders frames from a `.dur` to a PNG contact sheet. |
| `validate_dur.py` | Checks the format, row widths, colours, loop seamlessness and Durdraw loading. |
| `test_frames.py` | Renders selected frames only, for quick visual iteration. |
| `preview-256.png`, `preview-16.png`, `preview-256-hd.png` | Preview contact sheets. |
| `scene.png` | Full-resolution still (1280×800) of the source render, for reference. |

## Requirements

- Python 3.10+
- `numpy`
- `Pillow` (PIL)

On Arch:

```sh
sudo pacman -S python-numpy python-pillow
```

## Generate

```sh
# 256-colour, 160x50 (the defaults)
python3 make_anubis.py

# 16-colour fallback
python3 make_anubis.py --colors 16

# full-screen for 1920x1080 with an 8x16 console font
python3 make_anubis.py --width 240 --height 67 --out anubis-256-240x67.dur

# custom size / timing
python3 make_anubis.py --width 120 --height 44 --frames 60 --fps 12 --colors 256
```

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--width` | `160` | canvas columns |
| `--height` | `50` | canvas rows |
| `--frames` | `90` | number of frames |
| `--fps` | `15` | playback rate stored in the file |
| `--colors` | `256` | `256` or `16` |
| `--shade` | `mosaic` | `mosaic` fills cell backgrounds; `glyph` uses foreground characters only. `16` always uses glyph shading. |
| `--out` | `anubis-<colors>-<w>x<h>.dur` | output path |

To match your actual console, use its size in cells:

```sh
# on a real VT, or from a terminal that reports the console size
tput cols
tput lines
```

On a 1920×1080 framebuffer with the kernel's default 8×16 font that is **240×67**.

## Preview and validate

```sh
python3 preview_dur.py anubis-256-160x50.dur preview-256.png --frames 1,24,53,70
python3 validate_dur.py anubis-256-160x50.dur anubis-16-160x50.dur
```

`validate_dur.py` uses Durdraw's own `open_json_dur_file()` so it catches parser
issues, not just structural ones.

## Install for ly

```sh
sudo install -m 644 anubis-256-160x50.dur /etc/ly/anubis.dur
sudoedit /etc/ly/config.ini
```

Set these options:

```ini
animation = dur_file
dur_file_path = /etc/ly/anubis.dur
animation_frame_delay = 5
animation_timeout_sec = 0

dur_offset_alignment = center
dur_x_offset = 0
dur_y_offset = 0

full_color = true
blank_box = false
```

Why these matter:

- **`full_color = true`** is required for a 256-colour `.dur`. ly 1.4.1 refuses a
  256-colour file when `full_color = false`. If you must run in 16-colour mode, use
  `anubis-16-160x50.dur` instead.
- **`blank_box = false`** makes the login box transparent, so the face is not hidden
  behind a filled rectangle. The box border and text are still drawn on top of the
  animation.
- **`animation_timeout_sec = 0`** keeps it running forever.
- **`dur_offset_alignment = center`** centres the art. Use `dur_y_offset` if you want to
  move it up or down, for example `dur_y_offset = -3` to lift the face above the login
  box.
- **`animation_frame_delay`** is the widget update interval in milliseconds; `5` is fine.
  The actual frame rate comes from the `.dur` file (`framerate`), so 90 frames at 15 fps
  is a 6-second loop.

After saving, restart ly (or log out to the display manager):

```sh
sudo systemctl restart ly
```

If ly rejects the file, check `/var/log/ly.log`. The most common causes are an
unsupported `formatVersion`, a 256-colour file with `full_color = false`, or a
`dur_file_path` pointing at the wrong file.

## Notes on the format

These files are gzipped JSON, **Durdraw format version 7** — the version ly 1.4.x
accepts. The generator handles the quirks that are easy to get wrong:

- `contents[y][x]` is row-major, and every row is exactly `sizeX` codepoints.
- `colorMap[x][y]` is **column-major** in v7, with `[fg, bg]` per cell.
- The files are ASCII-only, so a Linux console font cannot turn characters into `#`.
- 256-colour files use only xterm indices ≥ 16. ly maps indices 0–15 through an
  ANSI-ordered table, while Durdraw stores them in a different order; staying in the
  6×6×6 cube and the grayscale ramp avoids the mismatch entirely.
- Every time-dependent term completes an integer number of cycles over the frame count,
  so frame 0 and frame N are identical and the loop has no visible seam.

The animation uses `mosaic` shading in 256-colour mode: cell backgrounds carry the
smooth colour field and foreground glyphs add texture. 16-colour mode falls back to
classic ANSI-style glyph shading, because nearest-colour mapping turns the soft cowl
into a flat gray slab.

## Credits

Fan art. *Stargate SG-1* and Anubis are the property of MGM. This project only
redistributes original generated artwork and code.
