"""Timestamped backups of allocator.db, so it can be recovered if something breaks."""
from datetime import datetime
import shutil

from paths import BACKUP_DIR, DB_PATH


def backup_db():
    if not DB_PATH.exists():
        return
    
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copyfile(DB_PATH, BACKUP_DIR / f"allocator_{timestamp}.db")
