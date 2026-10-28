#!/bin/bash
# Removes Mouthpiece. Keeps your voices and generations (~/.local/share/mouthpiece) and the model
# (~/.cache/huggingface); delete those by hand if you want them gone too.
app=${MOUTHPIECE_HOME:-$HOME/.local/lib/mouthpiece}
[ -x "$HOME/.local/bin/mouthpiece" ] && "$HOME/.local/bin/mouthpiece" stop >/dev/null 2>&1
rm -rf "$app"
rm -f "$HOME/.local/bin/mouthpiece" "$HOME/.local/share/applications/mouthpiece.desktop" \
  "$HOME/.local/share/icons/hicolor/256x256/apps/mouthpiece.png" "$HOME/.local/share/icons/hicolor/scalable/apps/mouthpiece.svg"
echo "Mouthpiece removed. Your voices are still in ~/.local/share/mouthpiece."
