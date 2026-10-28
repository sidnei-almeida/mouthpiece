#!/bin/bash
# One-time setup: Python 3.12 venv with PyTorch for Intel GPUs (XPU, Arc B580), Qwen3-TTS and the
# web server. qwen-tts depends on the CUDA build of PyTorch, so it goes in without its dependencies
# and those are listed here. Model weights download on first start (~4 GB, Hugging Face cache).
set -euo pipefail
cd "$(dirname "$0")"
uv=$(command -v uv || true)
[ -x "$uv" ] && "$uv" --version >/dev/null 2>&1 || uv=$(ls ~/.local/share/mise/installs/uv/*/uv-*/uv 2>/dev/null | tail -1)

"$uv" venv --python 3.12 .venv
"$uv" pip install --python .venv/bin/python torch torchaudio --index-url https://download.pytorch.org/whl/xpu
"$uv" pip install --python .venv/bin/python transformers==4.57.3 accelerate==1.12.0 librosa soundfile sox \
  onnxruntime einops huggingface_hub fastapi uvicorn
"$uv" pip install --python .venv/bin/python --no-deps qwen-tts
