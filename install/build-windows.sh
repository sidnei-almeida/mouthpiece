#!/bin/bash
# Builds dist/Mouthpiece-Setup-<version>.exe on Linux, through Wine and Inno Setup 6.
# Needs Inno Setup installed in the Wine prefix once:
#   curl -L -o /tmp/innosetup.exe https://jrsoftware.org/download.php/is.exe
#   wine /tmp/innosetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
set -euo pipefail
cd "$(dirname "$0")/.."
iscc=$(find "${WINEPREFIX:-$HOME/.wine}/drive_c" -iname ISCC.exe 2>/dev/null | head -1)
[ -n "$iscc" ] || { echo "Inno Setup not found in Wine; see the comment at the top of this script" >&2; exit 1; }
python3 brand/build.py >/dev/null
WINEDEBUG=-all wine "$iscc" /Q "install\\windows\\mouthpiece.iss"
ls -lh dist/*.exe
