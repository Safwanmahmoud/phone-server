"""Single-password sign-in. The password is set on the phone with `python -m server.cli set-password`."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from .config import PASSWORD_FILE, SECRET_FILE

ITERATIONS = 600_000


def secret_key() -> str:
    """Signs the session cookie. Created once and kept in the data folder."""
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_FILE.write_text(key)
    SECRET_FILE.chmod(0o600)
    return key


def _record() -> dict | None:
    try:
        return json.loads(PASSWORD_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def is_configured() -> bool:
    return _record() is not None


def set_password(password: str) -> None:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    tmp = PASSWORD_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hash": digest.hex(), "salt": salt.hex(), "iterations": ITERATIONS}))
    tmp.chmod(0o600)
    tmp.replace(PASSWORD_FILE)


def verify(password: str) -> bool:
    rec = _record()
    if not rec or not password:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(rec["salt"]), rec["iterations"])
    return hmac.compare_digest(digest.hex(), rec["hash"])


def password_version() -> str | None:
    """Changes whenever the password does, which signs everyone out."""
    rec = _record()
    return rec["salt"][:16] if rec else None


def is_signed_in(session: dict) -> bool:
    version = password_version()
    return bool(version and session.get("auth") and session.get("pv") == version)


class LoginLimiter:
    """At most MAX wrong passwords per address in WINDOW seconds."""

    WINDOW = 600
    MAX = 5

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self._fails.get(ip, []) if now - t < self.WINDOW]
        self._fails[ip] = recent
        return len(recent) >= self.MAX

    def fail(self, ip: str) -> None:
        self._fails.setdefault(ip, []).append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)
