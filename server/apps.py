"""Validation and shaping of app records, plus the API error types."""
from __future__ import annotations

import asyncio
import re
import socket
from asyncio.subprocess import DEVNULL, PIPE

from . import db
from .config import APP_PORTS, GIT, RESERVED_PORTS, git_env


class ApiError(Exception):
    status = 400

    def __init__(self, message: str, status: int | None = None, extra: dict | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status
        self.extra = extra or {}  # sent alongside "error" in the JSON reply


class Invalid(ApiError):
    status = 400


class NotFound(ApiError):
    status = 404


class Conflict(ApiError):
    status = 409


NAME_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,30}[a-z0-9])?$")
RESERVED_NAMES = {"all"}  # `pm2 stop all` would mean every process


def validate_name(value) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not NAME_RE.match(name):
        raise Invalid("Use 1–32 lowercase letters, numbers and dashes for the name, starting with a letter.")
    if name in RESERVED_NAMES or name.startswith("ps-"):
        raise Invalid(f"{name} is reserved. Pick another name.")
    return name


# https://…, ssh://…, git@host:path, or a path on the phone (handy for testing).
REPO_RE = re.compile(r"^(?:https?://\S+|ssh://\S+|[\w.-]+@[\w.-]+:\S+|/\S+)$")


def validate_repo(value) -> str:
    url = value.strip() if isinstance(value, str) else ""
    if not url:
        raise Invalid("Enter the repository URL.")
    # "::" blocks git's ext:: and fd:: transports, which run commands.
    if len(url) > 500 or url.startswith("-") or "::" in url or not REPO_RE.match(url):
        raise Invalid("Use an HTTPS or SSH Git URL, like https://github.com/you/project or git@github.com:you/project.git.")
    return url


BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


def validate_branch(value) -> str:
    branch = value.strip() if isinstance(value, str) else ""
    if not branch:
        raise Invalid("Enter a branch.")
    if (not BRANCH_RE.match(branch) or branch.startswith(("-", "/")) or ".." in branch
            or branch.endswith((".lock", "/", "."))):
        raise Invalid("That isn't a valid branch name.")
    return branch


def validate_cmd(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Invalid("The start command must be text.")
    cmd = value.strip()
    if "\n" in cmd or "\r" in cmd:
        raise Invalid("Keep the start command on one line.")
    if len(cmd) > 1000:
        raise Invalid("The start command is too long.")
    return cmd


ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_ENV = {"PORT", "VIRTUAL_ENV"}


def parse_env(text) -> dict[str, str]:
    """KEY=value per line; blank lines and # comments are skipped; `export ` and quotes are allowed."""
    if text is None:
        return {}
    if not isinstance(text, str):
        raise Invalid("Environment variables must be text.")
    env: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep:
            raise Invalid(f"Line {n}: use KEY=value.")
        if not ENV_KEY_RE.match(key):
            raise Invalid(f"Line {n}: {key or '(empty)'} isn't a valid variable name.")
        if key in RESERVED_ENV:
            hint = " Use the port field instead." if key == "PORT" else ""
            raise Invalid(f"Line {n}: {key} is set by the dashboard.{hint}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[key] = value
    if len(env) > 200:
        raise Invalid("That's too many variables.")
    return env


def validate_port(value, app_name: str | None = None) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise Invalid("The port must be a number.") from None
    if not 1024 <= port <= 65535:
        raise Invalid("Use a port between 1024 and 65535.")
    if port in RESERVED_PORTS:
        raise Invalid(f"Port {port} is used by the dashboard.")
    if port in db.used_ports(exclude=app_name):
        raise Invalid(f"Another app already uses port {port}.")
    return port


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def allocate_port() -> int:
    used = db.used_ports()
    for port in APP_PORTS:
        if port not in used and not port_in_use(port):
            return port
    raise Conflict(f"No free ports left between {APP_PORTS.start} and {APP_PORTS.stop - 1}.")


async def check_repo(url: str, branch: str | None = None) -> str:
    """Confirm the phone can read the repository. Returns the branch (the default one if none was given)."""
    if branch is None:
        args = [GIT, "ls-remote", "--symref", url, "HEAD"]
    else:
        args = [GIT, "ls-remote", "--heads", url, branch]
    proc = await asyncio.create_subprocess_exec(*args, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=git_env())
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 40)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise Invalid("Timed out reaching the repository.") from None
    if proc.returncode != 0:
        raise Invalid(git_error(err.decode(errors="replace")))
    text = out.decode(errors="replace")
    if branch is None:
        for line in text.splitlines():
            if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
                return line[len("ref: refs/heads/"):-len("\tHEAD")]
        raise Invalid("Couldn't find the repository's default branch. Enter the branch name.")
    if f"refs/heads/{branch}" not in text.split():
        raise Invalid(f"The repository has no branch called {branch}.")
    return branch


def git_error(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip() and not ln.startswith("Warning: Permanently added")]
    detail = " ".join(lines)[-300:] or "git couldn't read it."
    low = stderr.lower()
    if any(s in low for s in ("permission denied", "could not read username", "authentication failed", "repository not found")):
        return ("Couldn't read the repository. If it's private, add the phone's SSH key to GitHub on the "
                f"Settings page and use the git@github.com:… URL. ({detail})")
    return f"Couldn't reach the repository: {detail}"


def public(app: dict, process: dict | None, last_deploy: dict | None, active: bool, include_env: bool = False) -> dict:
    out = {k: app[k] for k in ("name", "repo_url", "branch", "start_cmd", "detected_cmd", "port", "created_at", "updated_at")}
    out["domains"] = app.get("domains", [])
    out["process"] = process
    out["last_deploy"] = last_deploy
    out["active_deploy"] = active
    if include_env:
        out["env"] = app["env"]
    return out
