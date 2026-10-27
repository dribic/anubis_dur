#!/bin/sh
# Install the GIF-based Anubis animation as the ly display-manager background.
#
# Run as root:
#     sudo ./install-ly.sh
#     sudo ./install-ly.sh anubis-gif-256-160x50.dur
#
# It copies the animation to /etc/ly/anubis.dur and rewrites the dur options in
# /etc/ly/config.ini.  The first run saves the original config as config.ini.bak;
# later runs reuse it, so the backup is never overwritten by our own edits.
set -eu

LY_DIR="${LY_DIR:-/etc/ly}"
SRC_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DUR_NAME="${1:-anubis-gif-256-240x67.dur}"

if [ ! -f "$SRC_DIR/$DUR_NAME" ]; then
    echo "error: $SRC_DIR/$DUR_NAME not found" >&2
    echo "       run 'make gif' first" >&2
    exit 1
fi

if [ ! -f "$LY_DIR/config.ini" ]; then
    echo "error: $LY_DIR/config.ini not found" >&2
    exit 1
fi

install -m 644 "$SRC_DIR/$DUR_NAME" "$LY_DIR/anubis.dur"

python3 - "$LY_DIR/config.ini" "$LY_DIR/anubis.dur" <<'PY'
import os
import re
import shutil
import sys

config_path = sys.argv[1]
dur_path = sys.argv[2]

settings = {
    "animation": "dur_file",
    "dur_file_path": dur_path,
    "animation_frame_delay": "5",
    "animation_timeout_sec": "0",
    "dur_offset_alignment": "center",
    "blank_box": "false",
    "full_color": "true",
}

with open(config_path, encoding="utf-8") as handle:
    text = handle.read()

# Keep the pristine config from the first run, not a copy of our own output.
backup_path = config_path + ".bak"
if not os.path.exists(backup_path):
    shutil.copy2(config_path, backup_path)

changed = {}
for key, value in settings.items():
    pattern = re.compile(rf"(?m)^{re.escape(key)}[ \t]*=[^\n]*$")
    replacement = f"{key} = {value}"
    new_text, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        sys.exit(f"error: no active '{key} =' line in {config_path}")
    if new_text != text:
        changed[key] = value
    text = new_text

with open(config_path, "w", encoding="utf-8") as handle:
    handle.write(text)

for key in settings:
    mark = " (changed)" if key in changed else ""
    print(f"  {key} = {settings[key]}{mark}")
PY

echo
echo "installed $DUR_NAME -> $LY_DIR/anubis.dur"
echo "config backup: $LY_DIR/config.ini.bak"
echo
echo "Restart ly to see it (this ends the current session):"
echo "    systemctl restart ly@tty2.service"
echo
echo "If ly rejects the file, check /var/log/ly.log; the usual cause is"
echo "full_color = false or a dur_file_path pointing at the wrong file."
