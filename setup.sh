#!/bin/bash
# One-time setup: Python 3.12 venv with PyTorch for Intel GPUs (XPU, Arc B580), Qwen3-TTS and the
# web server. qwen-tts depends on the CUDA build of PyTorch, so it goes in without its dependencies
# and those are listed here. Model weights download on first start (~4 GB, Hugging Face cache).
set -euo pipefail
cd "$(dirname "$0")"
uv=$(command -v uv || true)
[ -x "$uv" ] && "$uv" --version >/dev/null 2>&1 || uv=$(ls ~/.local/share/mise/installs/uv/*/uv-*/uv 2>/dev/null | tail -1)

"$uv" venv --python 3.12 .venv
# Pinned to the versions this was built and tested with (2026-10-28); upgrade on purpose, then retest.
"$uv" pip install --python .venv/bin/python torch==2.14.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/xpu
"$uv" pip install --python .venv/bin/python transformers==4.57.3 accelerate==1.12.0 librosa==1.0.0 \
  soundfile==0.14.0 sox==1.5.0 onnxruntime==1.31.1 einops==0.8.2 huggingface_hub==0.36.2 \
  fastapi==0.162.0 uvicorn==0.54.0
"$uv" pip install --python .venv/bin/python --no-deps qwen-tts==0.1.1
