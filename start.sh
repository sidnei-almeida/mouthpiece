#!/bin/bash
# Starts the voice studio on http://127.0.0.1:7860 and opens it in the browser once the server is up.
# The model then loads on the GPU in the background (~10 s once cached; the page shows when it's ready).
# Don't run a game at the same time: it can starve the Arc and make generation hang.
cd "$(dirname "$0")"
( for _ in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:7860/api/status && break; sleep 0.5; done
  xdg-open http://127.0.0.1:7860 >/dev/null 2>&1 ) &
exec .venv/bin/uvicorn server:app --host 127.0.0.1 --port 7860
