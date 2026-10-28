#!/bin/bash
# Linux setup: a Python 3.12 venv with the PyTorch build for this machine's GPU (Intel Arc -> XPU,
# NVIDIA -> CUDA, otherwise CPU), Qwen3-TTS and the server, then the model (~4 GB, pinned revision).
# qwen-tts depends on the CUDA build of PyTorch, so it goes in without its dependencies; they are
# listed here instead. MOUTHPIECE_BACKEND=xpu|cu130|cu126|cpu overrides the detection.
set -euo pipefail
cd "$(dirname "$0")"
uv=$(command -v uv || true)
[ -n "$uv" ] && "$uv" --version >/dev/null 2>&1 || uv=$(ls ~/.local/share/mise/installs/uv/*/uv-*/uv 2>/dev/null | tail -1)
[ -x "$uv" ] || { echo "Mouthpiece needs uv: https://docs.astral.sh/uv/" >&2; exit 1; }

backend=${MOUTHPIECE_BACKEND:-}
if [ -z "$backend" ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
    driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
    backend=$([ "${driver:-0}" -ge 580 ] && echo cu130 || echo cu126)
  elif lspci 2>/dev/null | grep -iE 'vga|display|3d' | grep -qi intel && [ -e /dev/dri/renderD128 ]; then
    backend=xpu
  else
    backend=cpu
  fi
fi
echo "backend: $backend"

# Pinned to the versions this was built and tested with (2026-10-28); upgrade on purpose, then retest.
"$uv" venv --python 3.12 .venv
"$uv" pip install --python .venv/bin/python torch==2.14.1 torchaudio==2.11.0 --index-url "https://download.pytorch.org/whl/$backend"
"$uv" pip install --python .venv/bin/python -r requirements.txt
"$uv" pip install --python .venv/bin/python --no-deps qwen-tts==0.1.1
.venv/bin/python -c "
from huggingface_hub import snapshot_download
import server_model
snapshot_download(server_model.MODEL_ID, revision=server_model.MODEL_REVISION)
print('model ready')"
