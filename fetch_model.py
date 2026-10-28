"""Downloads the voice model at its pinned revision (~4 GB) into the Hugging Face cache. Run by the
setup scripts; a file rather than inline `python -c`, which Windows PowerShell 5.1 mangles (it drops
the double quotes from arguments it passes to programs)."""
from huggingface_hub import snapshot_download

from server_model import MODEL_ID, MODEL_REVISION

print(snapshot_download(MODEL_ID, revision=MODEL_REVISION))
