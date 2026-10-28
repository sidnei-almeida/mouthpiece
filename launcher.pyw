"""What the Start menu / desktop shortcut runs: starts the Mouthpiece server if needed (no console
window on Windows, thanks to pythonw and the .pyw extension) and opens the app in the browser. The
page shows the model loading; the server shuts itself down after 20 idle minutes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cli  # noqa: E402

cli.cmd_open(None)
