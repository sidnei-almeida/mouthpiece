#!/bin/bash
# Installs Mouthpiece for the current user, from the release tarball (run it from the extracted folder):
# the app in ~/.local/lib/mouthpiece, the `mouthpiece` command, the app-menu entry and icon. Then it
# downloads Python, the PyTorch build for this GPU and the voice model: a few GB, several minutes.
#   ./install.sh                  (MOUTHPIECE_BACKEND=xpu|cu130|cu126|cpu to skip GPU detection)
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
app=${MOUTHPIECE_HOME:-$HOME/.local/lib/mouthpiece}
bin=$HOME/.local/bin
mkdir -p "$bin"

if ! { command -v uv >/dev/null && uv --version >/dev/null 2>&1; }; then
  echo ">> uv (Python manager)"
  [ -x "$bin/uv" ] || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$bin" sh
  export PATH="$bin:$PATH"
fi

echo ">> app -> $app"
mkdir -p "$app"
cp -r "$src"/. "$app"/
rm -f "$app/install.sh"

echo ">> Python, PyTorch and the voice model"
"$app/setup.sh"

echo ">> command, menu entry, icon"
ln -sf "$app/cli.py" "$bin/mouthpiece"
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps" "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$app/brand/icon/icon-256.png" "$HOME/.local/share/icons/hicolor/256x256/apps/mouthpiece.png"
cp "$app/brand/icon/icon.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/mouthpiece.svg"
cat > "$HOME/.local/share/applications/mouthpiece.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Mouthpiece
GenericName=Text to speech
Comment=your voice, typed.
Exec=$app/start.sh
Icon=mouthpiece
Terminal=false
Categories=AudioVideo;Audio;
Keywords=voice;tts;narration;voz;
DESKTOP

echo
echo "Done. Open Mouthpiece from the app menu, or run: mouthpiece open"
case ":$PATH:" in *":$bin:"*) ;; *) echo "(add $bin to your PATH to use the mouthpiece command)";; esac
