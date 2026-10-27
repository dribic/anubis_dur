PYTHON ?= python3

.PHONY: all 256 16 hd gif gifhd install preview validate clean

all: 256 16 gif gifhd

256:
	$(PYTHON) make_anubis.py --colors 256 --width 160 --height 50 \
		--frames 90 --fps 15 --out anubis-256-160x50.dur

16:
	$(PYTHON) make_anubis.py --colors 16 --width 160 --height 50 \
		--frames 90 --fps 15 --out anubis-16-160x50.dur

hd:
	$(PYTHON) make_anubis.py --colors 256 --width 240 --height 67 \
		--frames 90 --fps 15 --out anubis-256-240x67.dur

gif:
	$(PYTHON) make_anubis_gif.py --width 160 --height 50 \
		--out anubis-gif-256-160x50.dur

# Full screen on a 1920x1080 console with the default 8x16 font (240x67 cells).
gifhd:
	$(PYTHON) make_anubis_gif.py --width 240 --height 67 \
		--out anubis-gif-256-240x67.dur

install:
	sudo ./install-ly.sh

preview:
	$(PYTHON) preview_dur.py anubis-256-160x50.dur preview-256.png --frames 1,24,53,70
	$(PYTHON) preview_dur.py anubis-16-160x50.dur preview-16.png --frames 1,24,53,70
	$(PYTHON) preview_dur.py anubis-256-240x67.dur preview-256-hd.png --frames 1,53
	$(PYTHON) preview_dur.py anubis-gif-256-160x50.dur preview-gif-256.png --frames 1,22,44,66
	$(PYTHON) preview_dur.py anubis-gif-256-240x67.dur preview-gif-256-hd.png --frames 1,22,44,66

validate:
	$(PYTHON) validate_dur.py anubis-256-160x50.dur anubis-16-160x50.dur \
		anubis-256-240x67.dur --scene-loop
	$(PYTHON) validate_dur.py anubis-gif-256-160x50.dur
	$(PYTHON) validate_dur.py anubis-gif-256-240x67.dur

clean:
	rm -rf __pycache__ test.dur
