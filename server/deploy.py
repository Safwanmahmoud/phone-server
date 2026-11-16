"""Deploys: fetch the code, install requirements, start it under PM2, and check that it answers."""
from __future__ import annotations

import asyncio
import codecs
import contextlib
import hashlib
import json
import re
import shlex
import shutil
import time
import traceback
from asyncio.subprocess import DEVNULL, PIPE, STDOUT
from dataclasses import dataclass
from pathlib import Path

from . import db, pm2
from .apps import ApiError
from .config import APPS_DIR, BASH, DATA, GIT, HOME, PYTHON, clean_env, git_env


class DeployError(ApiError):
    status = 409


# One deploy at a time: pip installs are heavy on a phone.
DEPLOY_LOCK = asyncio.Lock()
_TASKS: set[asyncio.Task] = set()


@dataclass(frozen=True)
class AppPaths:
    root: Path
    repo: Path
    venv: Path
    logs: Path
    app_log: Path
    eco: Path
    deps_stamp: Path


def paths(name: str) -> AppPaths:
    root = APPS_DIR / name
    return AppPaths(
        root=root,
        repo=root / "repo",
        venv=root / "venv",
        logs=root / "logs",
        app_log=root / "logs" / "app.log",
        eco=root / "pm2.json",
        deps_stamp=root / "deps.stamp",
    )


def deploy_log_path(name: str, dep_id: int) -> Path:
    return paths(name).logs / f"deploy-{dep_id}.log"


class DeployLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        self._f.write(text)
        self._f.flush()

    def line(self, text: str = "") -> None:
        self.write(text + "\n")

    def step(self, title: str) -> None:
        self.line(f"\n── {title}")

    def close(self) -> None:
        self._f.close()


_CREDS = re.compile(r"(https?://)[^/@\s]+@")


def _mask(text: str) -> str:
    return _CREDS.sub(r"\1***@", text)


def _show(cmd: list[str]) -> str:
    text = shlex.join(cmd).replace(str(DATA), "~/.phone-server").replace(str(HOME), "~")
    return _mask(text)


async def _run(cmd: list[str], log: DeployLog, *, cwd: Path | None = None, env: dict | None = None,
               timeout: float = 900) -> int:
    log.line(f"$ {_show(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, env=env, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    async def pump() -> None:
        while chunk := await proc.stdout.read(8192):
            log.write(_mask(decoder.decode(chunk)))
        log.write(decoder.decode(b"", final=True))

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        log.line(f"\nStopped: this step took longer than {int(timeout // 60)} minutes.")
        return -1
    return proc.returncode


async def _must(cmd: list[str], log: DeployLog, what: str, **kw) -> None:
    code = await _run(cmd, log, **kw)
    if code != 0:
        raise DeployError(f"{what} failed (exit code {code}).")


async def _capture(cmd: list[str], env: dict) -> str:
    proc = await asyncio.create_subprocess_exec(*cmd, env=env, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL)
    out, _ = await proc.communicate()
    return out.decode(errors="replace").strip()


def start_deploy(name: str, trigger: str) -> dict:
    if db.active_deployment(name):
        raise DeployError("A deploy is already running for this app.")
    dep = db.create_deployment(name, trigger)
    task = asyncio.create_task(_deploy_task(dep["id"], name))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return dep


async def _deploy_task(dep_id: int, name: str) -> None:
    log = DeployLog(deploy_log_path(name, dep_id))
    try:
        if DEPLOY_LOCK.locked():
            log.line("Waiting for another deploy to finish…")
        async with DEPLOY_LOCK:
            db.update_deployment(dep_id, status="running", started_at=time.time())
            log.line(f"Deploy #{dep_id} of {name}, started {time.strftime('%Y-%m-%d %H:%M:%S')}")
            warning = await _deploy(dep_id, name, log)
            if warning:
                log.line(f"\n! {warning}")
            log.line("\n✓ Deployed.")
            db.update_deployment(dep_id, status="success", warning=warning, finished_at=time.time())
    except DeployError as e:
        log.line(f"\n✗ {e}")
        db.update_deployment(dep_id, status="failed", error=str(e), finished_at=time.time())
    except Exception as e:  # keep the dashboard alive and the reason visible
        log.line("\n✗ Unexpected error:\n" + traceback.format_exc())
        db.update_deployment(dep_id, status="failed", error=f"Unexpected error: {e}", finished_at=time.time())
    finally:
        log.close()
        pm2.invalidate()


async def _deploy(dep_id: int, name: str, log: DeployLog) -> str | None:
    app = db.get_app(name)
    p = paths(name)
    p.logs.mkdir(parents=True, exist_ok=True)
    genv = git_env()

    log.step("Fetching code")
    if (p.repo / ".git").is_dir():
        await _must([GIT, "-C", str(p.repo), "remote", "set-url", "origin", app["repo_url"]], log, "Updating the remote", env=genv)
        await _must([GIT, "-C", str(p.repo), "fetch", "--prune", "origin", app["branch"]], log, "git fetch", env=genv, timeout=600)
        await _must([GIT, "-C", str(p.repo), "reset", "--hard", "FETCH_HEAD"], log, "git reset", env=genv)
    else:
        if p.repo.exists():
            shutil.rmtree(p.repo)  # left over from a clone that didn't finish
        await _must([GIT, "clone", "--branch", app["branch"], "--single-branch", "--", app["repo_url"], str(p.repo)],
                    log, "git clone", env=genv, timeout=900)
    sha, _, subject = (await _capture([GIT, "-C", str(p.repo), "log", "-1", "--format=%H%x09%s"], genv)).partition("\t")
    db.update_deployment(dep_id, commit_sha=sha or None, commit_msg=subject[:200] or None)
    log.line(f"At {sha[:7]} {subject}")

    log.step("Installing requirements")
    venv_python = p.venv / "bin" / "python"
    if not venv_python.exists():
        await _must([PYTHON, "-m", "venv", str(p.venv)], log, "Creating the virtual environment", env=clean_env())
    venv_env = clean_env({"VIRTUAL_ENV": str(p.venv), "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
                          "PYTHONUNBUFFERED": "1"})
    venv_env["PATH"] = f"{p.venv / 'bin'}:{venv_env['PATH']}"
    install, stamp = _install_plan(p, sha)
    if install is None:
        log.line("No requirements.txt, pyproject.toml or setup.py. Nothing to install.")
    elif p.deps_stamp.exists() and p.deps_stamp.read_text() == stamp:
        log.line("Requirements haven't changed since the last deploy. Skipping the install.")
    else:
        p.deps_stamp.unlink(missing_ok=True)
        await _must([str(venv_python), "-m", "pip", "install", *install], log, "pip install",
                    cwd=p.repo, env=venv_env, timeout=3600)
        p.deps_stamp.write_text(stamp)

    log.step("Start command")
    detected = detect_start_cmd(p.repo, p.venv) or ""
    db.update_app(name, detected_cmd=detected)
    app = db.get_app(name)
    if app["start_cmd"]:
        log.line(f"Using your start command: {app['start_cmd']}")
    elif detected:
        log.line(f"Detected: {detected}")
    else:
        raise DeployError("Couldn't work out how to start this app. Add a Procfile with a web: line, "
                          "or set a start command in the app's Settings, then redeploy.")

    log.step("Starting")
    try:
        await start_process(app)
    except pm2.PM2Error as e:
        raise DeployError(f"PM2 couldn't start the app: {e}") from None
    log.line(f"Started under PM2 as {name}, port {app['port']}.")

    log.step("Checking it's up")
    return await _wait_until_up(app, log)


def _install_plan(p: AppPaths, sha: str) -> tuple[list[str] | None, str]:
    req = p.repo / "requirements.txt"
    if req.is_file():
        return ["-r", "requirements.txt"], "req:" + hashlib.sha256(req.read_bytes()).hexdigest()
    for marker in ("pyproject.toml", "setup.py"):
        if (p.repo / marker).is_file():
            return ["."], f"pkg:{sha}"  # the package is the code, so reinstall on every new commit
    return None, ""


def detect_start_cmd(repo: Path, venv: Path) -> str | None:
    procfile = repo / "Procfile"
    if procfile.is_file():
        for line in procfile.read_text(errors="replace").splitlines():
            kind, sep, cmd = line.partition(":")
            if sep and kind.strip() == "web" and cmd.strip():
                return cmd.strip()
    candidates = (("app/main.py", "app.main"), ("main.py", "main"), ("app.py", "app"),
                  ("server.py", "server"), ("asgi.py", "asgi"), ("wsgi.py", "wsgi"))
    for rel, module in candidates:
        f = repo / rel
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        if re.search(r"\b(FastAPI|Starlette|Quart)\(", text) or rel == "asgi.py":
            return f"python -m uvicorn {module}:app --host 0.0.0.0 --port $PORT"
        if re.search(r"\bFlask\(", text) or rel == "wsgi.py":
            if (venv / "bin" / "gunicorn").exists():
                return f"gunicorn --bind 0.0.0.0:$PORT --workers 2 {module}:app"
            return f"python -m flask --app {module} run --host 0.0.0.0 --port $PORT"
    for rel in ("main.py", "app.py", "server.py"):
        if (repo / rel).is_file():
            return f"python {rel}"
    return None


def write_ecosystem(app: dict, cmd: str) -> Path:
    p = paths(app["name"])
    env = clean_env(app["env"])
    env.update({"PORT": str(app["port"]), "VIRTUAL_ENV": str(p.venv), "PYTHONUNBUFFERED": "1"})
    env["PATH"] = f"{p.venv / 'bin'}:{env['PATH']}"
    # `exec` lets PM2 signal the app directly instead of a wrapping shell,
    # unless the command chains several steps.
    script = cmd if re.search(r"[;&|]", cmd) else f"exec {cmd}"
    spec = {"apps": [{
        "name": app["name"],
        "cwd": str(p.repo),
        "script": BASH,
        "args": ["-c", script],
        "interpreter": "none",
        "env": env,
        "out_file": str(p.app_log),
        "error_file": str(p.app_log),
        "merge_logs": True,
        "time": True,
        "autorestart": True,
        "min_uptime": 10000,
        "max_restarts": 10,
        "restart_delay": 3000,
        "kill_timeout": 8000,
    }]}
    p.logs.mkdir(parents=True, exist_ok=True)
    tmp = p.eco.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, indent=2))
    tmp.chmod(0o600)  # holds the app's environment variables
    tmp.replace(p.eco)
    return p.eco


async def start_process(app: dict) -> None:
    """(Re)start the app under PM2 with its current settings, without fetching code."""
    cmd = app["start_cmd"] or app["detected_cmd"]
    if not cmd:
        raise DeployError("This app has no start command. Set one in Settings.")
    if not paths(app["name"]).repo.is_dir():
        raise DeployError("Deploy this app first.")
    eco = write_ecosystem(app, cmd)
    await pm2.delete(app["name"])
    await pm2.start(eco)
    await pm2.save()


async def _wait_until_up(app: dict, log: DeployLog, timeout: float = 45.0) -> str | None:
    name, port = app["name"], app["port"]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    said_waiting = False
    while loop.time() < deadline:
        await asyncio.sleep(2)
        info = (await pm2.processes(max_age=0)).get(name)
        status = info["status"] if info else "missing"
        if status in ("errored", "stopped", "missing") or (info and info["restarts"] >= 2):
            log.line("The app keeps exiting. Last lines of its output:\n")
            log.write(tail(paths(name).app_log, 40))
            with contextlib.suppress(pm2.PM2Error):
                await pm2.stop(name)  # don't let it crash-loop and drain the battery
                await pm2.save()
            raise DeployError("The app exited right after starting, so it was stopped. See the output above.")
        if await _port_open(port):
            log.line(f"Answering on port {port}.")
            return None
        if not said_waiting:
            log.line(f"Running. Waiting for it to answer on port {port}…")
            said_waiting = True
    return (f"The app is running, but nothing answered on port {port} within {int(timeout)} seconds. "
            "Web apps should listen on 0.0.0.0:$PORT.")


async def _port_open(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1.5)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


def tail(path: Path, lines: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            data = f.read().decode(errors="replace")
    except FileNotFoundError:
        return "(no output)\n"
    out = "\n".join(data.splitlines()[-lines:])
    return (out or "(no output)") + "\n"


async def control(name: str, action: str) -> str:
    procs = await pm2.processes(max_age=0)
    if action == "stop":
        if name in procs:
            await pm2.stop(name)
        message = f"Stopped {name}."
    elif action in ("start", "restart"):
        if name in procs:
            await pm2.restart(name)  # also starts a stopped process
        elif paths(name).eco.exists():
            await start_process(db.get_app(name))
        else:
            raise DeployError("Deploy this app first.")
        message = f"Restarted {name}." if action == "restart" else f"Started {name}."
    else:
        raise ApiError("Unknown action.")
    await pm2.save()
    return message


async def remove(name: str) -> None:
    await pm2.delete(name)
    await pm2.save()
    await asyncio.to_thread(shutil.rmtree, paths(name).root, True)
    db.delete_app(name)
