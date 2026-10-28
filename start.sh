#!/bin/bash
# Linux: start Mouthpiece and open it in the browser (same as `mouthpiece open`). The server runs in
# the background and stops by itself after 20 idle minutes, or with `mouthpiece stop`.
# Don't run a game at the same time: it can starve the GPU and make generation hang.
cd "$(dirname "$0")"
exec .venv/bin/python launcher.pyw
