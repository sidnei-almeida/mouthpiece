#!/bin/bash
# After an install: create a voice from the test recording, speak a line, check the WAV. Proves the
# installed app is ready to use, not just installed. Used by the release workflow.
set -euo pipefail
mp=${MOUTHPIECE:-mouthpiece}
here=$(cd "$(dirname "$0")" && pwd)
"$mp" voice add "$here/fixtures/reference-en.wav" --name ci --lang en
out=$(mktemp -d)/smoke.wav
json=$("$mp" say "Hello from the release test." -o "$out" --voice ci-en.wav --json)
echo "$json"
python3 - "$out" "$json" <<'PY'
import json, sys, wave
w = wave.open(sys.argv[1])
assert w.getframerate() == 48000 and w.getnchannels() == 1 and w.getsampwidth() == 3, 'not 48 kHz mono 24-bit'
assert json.loads(sys.argv[2])['duration'] > 0.5, 'too short'
print('smoke test ok:', round(w.getnframes() / 48000, 1), 's')
PY
"$mp" stop
