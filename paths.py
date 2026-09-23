import os
import sys
from pathlib import Path


def get_app_dir():
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()

        if sys.platform == "darwin":
            # executable is inside JPR_Experimenter.app/Contents/MacOS/
            return executable.parents[3]

        return executable.parent

    return Path(__file__).resolve().parent

APP_DATA_DIR = get_app_dir()

DB_PATH = APP_DATA_DIR / "allocator.db"
BACKUP_DIR = APP_DATA_DIR / "backups"
MATERIAL_DIR = APP_DATA_DIR / "material"
USER_DIR = APP_DATA_DIR / "user"

LOCK_PATH = APP_DATA_DIR / "allocator.lock"