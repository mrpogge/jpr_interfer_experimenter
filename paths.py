import os
import sys
from pathlib import Path

def get_app_data_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    app_dir = base / "ExperimentAllocator"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir