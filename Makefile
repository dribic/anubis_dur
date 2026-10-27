PYTHON ?= python3

.PHONY: all 256 16 hd preview validate clean

all: 256 16

256:
	$(PYTHON) make_anubis.py --colors 256 --width 160 --height 50 \
		--frames 90 --fps 15 --out anubis-256-160x50.dur

16:
	$(PYTHON) make_anubis.py --colors 16 --width 160 --height 50 \
		--frames 90 --fps 15 --out anubis-16-160x50.dur

hd:
	$(PYTHON) make_anubis.py --colors 256 --width 240 --height 67 \
		--frames 90 --fps 15 --out anubis-256-240x67.dur

preview:
	$(PYTHON) preview_dur.py anubis-256-160x50.dur preview-256.png --frames 1,24,53,70
	$(PYTHON) preview_dur.py anubis-16-160x50.dur preview-16.png --frames 1,24,53,70
	$(PYTHON) preview_dur.py anubis-256-240x67.dur preview-256-hd.png --frames 1,53

validate:
	$(PYTHON) validate_dur.py anubis-256-160x50.dur anubis-16-160x50.dur anubis-256-240x67.dur

clean:
	rm -rf __pycache__ test.dur
