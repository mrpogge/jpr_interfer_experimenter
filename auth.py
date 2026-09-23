"""Experimenter accounts: registration requires admin approval before login
succeeds. Passwords are hashed with PBKDF2 + a random per-user salt."""
import hashlib
import os

from database import create_experimenter, get_experimenter

_ITERATIONS = 200_000


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS).hex()


def create_admin(username, password):
    """Bootstrap the first admin account (only meant to be called on first run)."""
    salt = os.urandom(16)
    create_experimenter(username, salt.hex(), _hash_password(password, salt), is_admin=True, is_active=True)


def register(username, password):
    """Creates a new, inactive experimenter account pending admin approval.
    Returns False if the username is already taken."""
    if get_experimenter(username) is not None:
        return False

    salt = os.urandom(16)
    create_experimenter(username, salt.hex(), _hash_password(password, salt), is_admin=False, is_active=False)
    return True


def login(username, password):
    """Returns one of: "not_found", "wrong_password", "inactive", or "ok".
    On "ok", also returns the experimenter record as a second value."""
    record = get_experimenter(username)
    if record is None:
        return "not_found", None

    salt = bytes.fromhex(record["salt"])
    if _hash_password(password, salt) != record["password_hash"]:
        return "wrong_password", None

    if not record["is_active"]:
        return "inactive", None

    return "ok", record
