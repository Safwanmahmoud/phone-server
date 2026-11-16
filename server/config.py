"""Paths and settings. Everything the dashboard writes lives under DATA (~/.phone-server)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
HOME = Path.home()
PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))

DATA = Path(os.environ.get("PS_DATA") or HOME / ".phone-server")
APPS_DIR = DATA / "apps"
LOGS_DIR = DATA / "logs"
DB_PATH = DATA / "phone-server.db"
SECRET_FILE = DATA / "secret.key"
PASSWORD_FILE = DATA / "password.json"

PUBLIC_PORT = int(os.environ.get("PS_PORT", "8080"))
DASHBOARD_PORT = int(os.environ.get("PS_DASHBOARD_PORT", "8000"))
APP_PORTS = range(8100, 8200)
RESERVED_PORTS = {PUBLIC_PORT, DASHBOARD_PORT, 8022}

# PM2 processes that make up the dashboard itself (see ecosystem.config.js).
SYSTEM_SERVICES = {
    "ps-dashboard": "Dashboard",
    "ps-agent": "PM2 bridge",
    "ps-caddy": "Web gateway (Caddy)",
    "ps-terminal": "Terminal (ttyd)",
}


def _bin(name: str) -> str:
    return shutil.which(name) or str(PREFIX / "bin" / name)


BASH = _bin("bash")
GIT = _bin("git")
PM2 = _bin("pm2")
NPM = _bin("npm")
SSH = _bin("ssh")
SSH_KEYGEN = _bin("ssh-keygen")
# The system Python, not the dashboard's own venv: app venvs are created from it.
PYTHON = str(PREFIX / "bin" / "python") if (PREFIX / "bin" / "python").exists() else _bin("python3")

# Variables a child process needs on Termux/Android. Everything else (PM2's own
# bookkeeping variables, the SSH session that first started PM2) is dropped so
# that apps and the pm2 CLI start from a clean environment.
_KEEP = {
    "HOME", "PATH", "PREFIX", "TMPDIR", "LANG", "LC_ALL", "TERM", "SHELL", "USER",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PM2_HOME", "BOOTCLASSPATH", "DEX2OATBOOTCLASSPATH",
    "SYSTEMSERVERCLASSPATH", "EXTERNAL_STORAGE", "ASEC_MOUNTPOINT",
}


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _KEEP or k.startswith(("ANDROID_", "TERMUX"))}
    env.setdefault("HOME", str(HOME))
    env.setdefault("PREFIX", str(PREFIX))
    env.setdefault("PATH", f"{PREFIX}/bin")
    env.setdefault("LANG", "en_US.UTF-8")
    if extra:
        env.update(extra)
    return env


def git_env() -> dict[str, str]:
    """Never prompt for credentials; fail fast so the UI can say why."""
    return clean_env({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20",
    })


def ensure_dirs() -> None:
    for d in (DATA, APPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
