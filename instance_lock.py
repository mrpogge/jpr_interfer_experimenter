"""Prevents two copies of the allocator from running against the same DB at once."""
import sys
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parent / ".instance.lock"
_lock_file = None


def acquire():
    """Returns True if this is the only running instance; keeps the lock held
    for the lifetime of the process (released automatically when it exits)."""
    global _lock_file
    _lock_file = open(LOCK_PATH, "w")

    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _lock_file.close()
        return False

    return True
