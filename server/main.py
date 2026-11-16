"""HTTP API and static UI for Phone Server.

Runs on 127.0.0.1 behind Caddy (see Caddyfile). Caddy also asks /api/auth/check
before letting anyone open the web terminal.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sqlite3
import time
from asyncio.subprocess import DEVNULL, PIPE

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, apps, auth, db, deploy, logs, pm2, system
from .apps import ApiError, Conflict, Invalid, NotFound
from .config import DATA, DASHBOARD_PORT, HOME, PUBLIC_PORT, SSH, SSH_KEYGEN, STATIC_DIR, SYSTEM_SERVICES, clean_env, ensure_dirs

ensure_dirs()
limiter = auth.LoginLimiter()
SSH_KEY = HOME / ".ssh" / "id_ed25519"
PUBLIC_API = {"/api/auth/status", "/api/auth/login", "/api/auth/check"}
CSRF_HEADER = "phone-server"


# ---------- helpers ----------

async def json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise Invalid("Send a JSON body.") from None
    if not isinstance(data, dict):
        raise Invalid("Send a JSON object.")
    return data


def int_param(request: Request, key: str) -> int | None:
    raw = request.query_params.get(key)
    if raw in (None, ""):
        return None
    if not raw.isdigit():
        raise Invalid(f"{key} must be a whole number.")
    return int(raw)


def require_app(name: str) -> dict:
    app = db.get_app(name)
    if not app:
        raise NotFound(f"There's no app called {name}.")
    return app


async def processes() -> tuple[dict, str | None]:
    try:
        return await pm2.processes(), None
    except pm2.PM2Error as e:
        return {}, str(e)


def ok(message: str | None = None, **extra) -> JSONResponse:
    return JSONResponse({"ok": True, **({"message": message} if message else {}), **extra})


# ---------- auth ----------

async def auth_status(request: Request) -> JSONResponse:
    return JSONResponse({"configured": auth.is_configured(), "authenticated": auth.is_signed_in(request.session)})


async def auth_check(request: Request) -> Response:
    """Caddy's forward_auth calls this before proxying the terminal."""
    return Response(status_code=200 if auth.is_signed_in(request.session) else 401)


async def login(request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not auth.is_configured():
        raise Conflict("No password is set yet. Set one on the phone first.")
    if limiter.blocked(ip):
        raise ApiError("Too many wrong passwords. Wait 10 minutes and try again.", 429)
    data = await json_body(request)
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    if not await run_in_threadpool(auth.verify, password):
        limiter.fail(ip)
        raise ApiError("Wrong password.", 401)
    limiter.reset(ip)
    request.session.clear()
    request.session.update(auth=True, pv=auth.password_version())
    return ok()


async def logout(request: Request) -> JSONResponse:
    request.session.clear()
    return ok()


# ---------- system ----------

async def get_system(request: Request) -> JSONResponse:
    procs, pm2_error = await processes()
    app_names = {a["name"] for a in db.list_apps()}
    app_procs = [p for name, p in procs.items() if name in app_names]
    return JSONResponse({
        **await run_in_threadpool(system.snapshot),
        "battery": await system.battery(),
        "apps": {
            "total": len(app_names),
            "running": sum(1 for p in app_procs if p["status"] == "online"),
            "memory": sum(p["memory"] for p in app_procs),
        },
        "dashboard_started_at": system.STARTED,
        "now": time.time(),
        "pm2_error": pm2_error,
    })


async def get_about(request: Request) -> JSONResponse:
    return JSONResponse({
        "version": __version__,
        "versions": await system.versions(),
        "data_dir": str(DATA).replace(str(HOME), "~"),
        "public_port": PUBLIC_PORT,
        "dashboard_port": DASHBOARD_PORT,
        "started_at": system.STARTED,
    })


# ---------- apps ----------

async def list_apps(request: Request) -> JSONResponse:
    procs, pm2_error = await processes()
    latest = db.latest_deployments()
    active = db.active_apps()
    items = [apps.public(a, procs.get(a["name"]), latest.get(a["name"]), a["name"] in active) for a in db.list_apps()]
    services = [{"name": n, "label": label, "process": procs.get(n)} for n, label in SYSTEM_SERVICES.items()]
    return JSONResponse({"apps": items, "services": services, "pm2_error": pm2_error})


async def create_app(request: Request) -> JSONResponse:
    data = await json_body(request)
    name = apps.validate_name(data.get("name"))
    if db.get_app(name):
        raise Conflict(f"An app called {name} already exists.")
    repo_url = apps.validate_repo(data.get("repo_url"))
    branch = data.get("branch").strip() if isinstance(data.get("branch"), str) else ""
    branch = apps.validate_branch(branch) if branch else None
    start_cmd = apps.validate_cmd(data.get("start_cmd"))
    env = apps.parse_env(data.get("env_text"))
    port = apps.validate_port(data["port"]) if data.get("port") else apps.allocate_port()
    branch = await apps.check_repo(repo_url, branch)
    try:
        db.insert_app(name=name, repo_url=repo_url, branch=branch, start_cmd=start_cmd, port=port, env=env)
    except sqlite3.IntegrityError:
        raise Conflict(f"An app called {name} already exists, or port {port} is taken.") from None
    dep = deploy.start_deploy(name, "created")
    app = db.get_app(name)
    return JSONResponse({"app": apps.public(app, None, dep, True), "deployment": dep}, status_code=201)


async def get_app(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    procs, pm2_error = await processes()
    recent = db.list_deployments(app["name"], limit=1)
    active = db.active_deployment(app["name"]) is not None
    body = apps.public(app, procs.get(app["name"]), recent[0] if recent else None, active, include_env=True)
    body["pm2_error"] = pm2_error
    return JSONResponse(body)


async def update_app(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    app = require_app(name)
    data = await json_body(request)
    fields: dict = {}
    if "repo_url" in data:
        fields["repo_url"] = apps.validate_repo(data["repo_url"])
    if "branch" in data:
        fields["branch"] = apps.validate_branch(data["branch"])
    if "start_cmd" in data:
        fields["start_cmd"] = apps.validate_cmd(data["start_cmd"])
    if "env_text" in data:
        fields["env"] = apps.parse_env(data["env_text"])
    if "port" in data:
        fields["port"] = apps.validate_port(data["port"], app_name=name)
    changed = {k: v for k, v in fields.items() if v != app[k]}
    if not changed:
        return ok("Nothing changed.")
    source_changed = bool({"repo_url", "branch"} & changed.keys())
    if source_changed:
        await apps.check_repo(changed.get("repo_url", app["repo_url"]), changed.get("branch", app["branch"]))
    db.update_app(name, **changed)

    message = "Saved."
    if {"start_cmd", "env", "port"} & changed.keys() and deploy.paths(name).eco.exists():
        if db.active_deployment(name):
            message = "Saved. The deploy that's running will use it."
        else:
            try:
                await deploy.start_process(db.get_app(name))
                message = "Saved and restarted."
            except (ApiError, pm2.PM2Error) as e:
                message = f"Saved, but couldn't restart: {e}"
    if source_changed:
        message += " Redeploy to pull the new code."
    return ok(message)


async def delete_app(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    require_app(name)
    if db.active_deployment(name):
        raise Conflict("Wait for the deploy to finish before deleting this app.")
    await deploy.remove(name)
    return ok(f"Deleted {name}.")


async def deploy_app(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    dep = deploy.start_deploy(app["name"], "manual")
    return JSONResponse({"deployment": dep}, status_code=202)


async def app_action(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    data = await json_body(request)
    action = data.get("action")
    if action not in ("start", "stop", "restart"):
        raise Invalid("action must be start, stop or restart.")
    if db.active_deployment(app["name"]):
        raise Conflict("A deploy is running. Wait for it to finish.")
    return ok(await deploy.control(app["name"], action))


async def app_logs(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    return JSONResponse(logs.read(deploy.paths(app["name"]).app_log, int_param(request, "offset"), tail=True))


async def clear_app_logs(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    path = deploy.paths(app["name"]).app_log
    if path.exists():
        path.write_bytes(b"")  # PM2 appends, so truncating in place is safe
    return ok("Logs cleared.")


async def list_deployments(request: Request) -> JSONResponse:
    app = require_app(request.path_params["name"])
    return JSONResponse({"deployments": db.list_deployments(app["name"])})


async def deployment_log(request: Request) -> JSONResponse:
    dep = db.get_deployment(request.path_params["id"])
    if not dep:
        raise NotFound("That deployment doesn't exist.")
    result = logs.read(deploy.deploy_log_path(dep["app"], dep["id"]), int_param(request, "offset") or 0, tail=False)
    result["deployment"] = dep
    result["done"] = dep["status"] in ("success", "failed") and not result["more"]
    return JSONResponse(result)


# ---------- settings ----------

async def get_ssh_key(request: Request) -> JSONResponse:
    pub = SSH_KEY.with_suffix(".pub")
    return JSONResponse({"public_key": pub.read_text().strip() if pub.exists() else None})


async def create_ssh_key(request: Request) -> JSONResponse:
    if SSH_KEY.exists():
        raise Conflict("This phone already has a key.")
    SSH_KEY.parent.mkdir(mode=0o700, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", f"phone-server ({system.device()['name']})", "-f", str(SSH_KEY),
        stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=clean_env(),
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise ApiError(f"ssh-keygen failed: {err.decode(errors='replace').strip()}", 500)
    return await get_ssh_key(request)


async def test_github(request: Request) -> JSONResponse:
    proc = await asyncio.create_subprocess_exec(
        SSH, "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
        "git@github.com", stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=clean_env(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 25)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return JSONResponse({"ok": False, "message": "GitHub didn't answer in time."})
    text = (out + err).decode(errors="replace")
    m = re.search(r"Hi ([^!]+)! You've successfully authenticated", text)
    if m:
        return JSONResponse({"ok": True, "message": f"Connected to GitHub as {m.group(1)}."})
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("Warning: Permanently added")]
    if any("Permission denied" in ln for ln in lines):
        return JSONResponse({"ok": False, "message": "GitHub doesn't know this key yet. Add it, then test again."})
    return JSONResponse({"ok": False, "message": lines[-1] if lines else "Couldn't connect to GitHub."})


async def index(request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------- middleware ----------

class Guard(BaseHTTPMiddleware):
    """Sign-in for /api, a custom header on writes (blocks cross-site forms), and safe defaults."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            if path not in PUBLIC_API and not auth.is_signed_in(request.session):
                return JSONResponse({"error": "Sign in first."}, status_code=401)
            if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != CSRF_HEADER:
                return JSONResponse({"error": "Missing X-Requested-With header."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


async def api_error(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


async def pm2_error(request: Request, exc: pm2.PM2Error) -> JSONResponse:
    return JSONResponse({"error": f"PM2: {exc}"}, status_code=502)


@contextlib.asynccontextmanager
async def lifespan(app):
    db.init()
    # Warm the slow one-time lookups (getprop, finding slow sensors) so the first page load is quick.
    warm = asyncio.create_task(run_in_threadpool(system.snapshot))
    yield
    warm.cancel()


routes = [
    Route("/", index),
    Route("/api/auth/status", auth_status),
    Route("/api/auth/check", auth_check),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/system", get_system),
    Route("/api/about", get_about),
    Route("/api/apps", list_apps),
    Route("/api/apps", create_app, methods=["POST"]),
    Route("/api/apps/{name}", get_app),
    Route("/api/apps/{name}", update_app, methods=["PATCH"]),
    Route("/api/apps/{name}", delete_app, methods=["DELETE"]),
    Route("/api/apps/{name}/deploy", deploy_app, methods=["POST"]),
    Route("/api/apps/{name}/action", app_action, methods=["POST"]),
    Route("/api/apps/{name}/logs", app_logs),
    Route("/api/apps/{name}/logs", clear_app_logs, methods=["DELETE"]),
    Route("/api/apps/{name}/deployments", list_deployments),
    Route("/api/deployments/{id:int}/log", deployment_log),
    Route("/api/settings/ssh-key", get_ssh_key),
    Route("/api/settings/ssh-key", create_ssh_key, methods=["POST"]),
    Route("/api/settings/github-test", test_github, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(SessionMiddleware, secret_key=auth.secret_key(), session_cookie="ps_session",
                   max_age=30 * 24 * 3600, same_site="lax", https_only=False),
        Middleware(Guard),
    ],
    exception_handlers={ApiError: api_error, pm2.PM2Error: pm2_error},
    lifespan=lifespan,
)
