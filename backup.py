"""Timestamped backups of allocator.db, so it can be recovered if something breaks."""
from datetime import datetime
from pathlib import Path
import shutil

from database import DB_PATH

BACKUP_DIR = Path(__file__).resolve().parent / "backups"


def backup_db():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copyfile(DB_PATH, BACKUP_DIR / f"allocator_{timestamp}.db")
