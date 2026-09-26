from __future__ import annotations
import os
import tempfile
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix="options-panel-browser-")
root = Path(_temp.name)
os.environ.update({
    "OPTIONS_APP_ROOT": str(Path(__file__).resolve().parents[2]),
    "OPTIONS_RUNTIME_DIR": str(root / "runtime"),
    "OPTIONS_US_DATA_DIR": str(root / "us-data"),
    "OPTIONS_LOG_DIR": str(root / "logs"),
    "OPTIONS_COLLECTOR_ENABLED": "false",
})

from options_panel.cli import main
raise SystemExit(main(["--host", "127.0.0.1", "--port", "8785"]))
