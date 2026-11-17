"""Public access for apps through a Cloudflare Tunnel.

The dashboard keeps a Cloudflare API token (Settings → Public access). With it, it
creates one tunnel for the phone and runs cloudflared under PM2 as ps-tunnel.
cloudflared only makes outgoing connections, so no router ports are opened.
Each domain listed on an app gets a DNS record pointing at the tunnel, and the
tunnel sends that hostname to the app's port.

The dashboard itself is never routed: only hostnames listed on apps are, and
Cloudflare answers anything else with a 404.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import db, pm2
from .apps import ApiError, Conflict, Invalid
from .config import CLOUDFLARED, DATA, LOGS_DIR, clean_env

API = "https://api.cloudflare.com/client/v4"
CONFIG_FILE = DATA / "cloudflare.json"   # API token, account and tunnel ids (mode 0600)
ECO_FILE = DATA / "tunnel.json"          # PM2 spec for cloudflared, holds the tunnel token (mode 0600)
LOG_FILE = LOGS_DIR / "ps-tunnel.log"
PROCESS = "ps-tunnel"
TUNNEL_NAME = "phone-server"
MAX_DOMAINS = 10

TOKEN_HELP = ("Create it at dash.cloudflare.com → My Profile → API Tokens with Account → Cloudflare Tunnel → Edit, "
              "Zone → DNS → Edit and Zone → Zone → Read.")


class CloudflareError(ApiError):
    status = 502


# ---------- Cloudflare API ----------

def _request(token: str, method: str, path: str, body: dict | None, query: dict | None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "phone-server"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        if not payload.get("errors"):
            raise CloudflareError(f"Cloudflare answered with HTTP {e.code}.") from None
    except ValueError:
        raise CloudflareError("Cloudflare sent a reply that isn't JSON.") from None
    except (urllib.error.URLError, OSError) as e:
        raise CloudflareError(f"Couldn't reach Cloudflare: {getattr(e, 'reason', e)}") from None
    if not payload.get("success"):
        errors = payload.get("errors") or []
        detail = "; ".join(f"{x.get('message')} ({x.get('code')})" for x in errors) or "the request failed"
        if any(x.get("code") in (9109, 10000, 6003, 6111, 1000) for x in errors):
            detail += f". Check the API token and its permissions. {TOKEN_HELP}"
        raise CloudflareError(f"Cloudflare: {detail}")
    return payload


async def cf(method: str, path: str, *, body: dict | None = None, query: dict | None = None,
             token: str | None = None) -> dict:
    if token is None:
        cfg = load()
        if not cfg:
            raise Conflict("Cloudflare isn't connected. Connect it in Settings → Public access.")
        token = cfg["api_token"]
    return await asyncio.to_thread(_request, token, method, path, body, query)


# ---------- stored settings ----------

def load() -> dict | None:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


# ---------- zones (the sites in the Cloudflare account) ----------

_zones: tuple[float, list[dict]] = (0.0, [])


async def zones(force: bool = False) -> list[dict]:
    global _zones
    if not force and time.monotonic() - _zones[0] < 60:
        return _zones[1]
    out, page = [], 1
    while True:
        p = await cf("GET", "/zones", query={"per_page": 50, "page": page})
        out += [{"id": z["id"], "name": z["name"], "status": z["status"], "name_servers": z.get("name_servers") or []}
                for z in p["result"]]
        if page >= (p.get("result_info") or {}).get("total_pages", 1):
            break
        page += 1
    _zones = (time.monotonic(), out)
    return out


def zone_for(host: str, zone_list: list[dict]) -> dict | None:
    matches = [z for z in zone_list if host == z["name"] or host.endswith("." + z["name"])]
    return max(matches, key=lambda z: len(z["name"])) if matches else None


# ---------- domains ----------

LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
HOST_RE = re.compile(rf"^(?:{LABEL}\.)+(?:[a-z]{{2,63}}|xn--[a-z0-9-]{{1,59}})$")


def validate_domains(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    if not isinstance(value, list):
        raise Invalid("Send the domains as a list.")
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise Invalid("Each domain must be text.")
        host = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].rstrip(".")
        if not host:
            continue
        if len(host) > 253 or not HOST_RE.match(host):
            raise Invalid(f"{raw.strip()} isn't a valid domain. Use a name like example.com or app.example.com.")
        if host not in out:
            out.append(host)
    if len(out) > MAX_DOMAINS:
        raise Invalid(f"Use at most {MAX_DOMAINS} domains per app.")
    return out


def _target(cfg: dict) -> str:
    return f"{cfg['tunnel_id']}.cfargotunnel.com"


def _site_hint(host: str) -> str:
    return ".".join(host.split(".")[-2:])


async def set_domains(app: dict, value, replace: bool = False) -> str:
    """Point the app's domains at the tunnel. Returns a message for the UI."""
    name = app["name"]
    new = validate_domains(value)
    for host in new:
        owner = db.domain_owner(host)
        if owner and owner != name:
            raise Conflict(f"{host} is already used by {owner}.")
    old = app["domains"]
    if new == old:
        return "Nothing changed."
    added = [d for d in new if d not in old]
    removed = [d for d in old if d not in new]
    cfg = load()
    if not cfg:
        raise Conflict("Connect Cloudflare first, in Settings → Public access.")
    zone_list = await zones(force=True)

    # Check everything before changing anything.
    plan: list[tuple[str, dict, list[dict]]] = []
    clashes: list[dict] = []
    for host in added:
        zone = zone_for(host, zone_list)
        if not zone:
            raise Invalid(f"{_site_hint(host)} isn't a site in your Cloudflare account yet. Add it at Cloudflare and "
                          "change its nameservers at Namecheap (Settings → Public access shows how), then try again.")
        records = (await cf("GET", f"/zones/{zone['id']}/dns_records", query={"name": host, "per_page": 100}))["result"]
        ours = any(r["type"] == "CNAME" and r["content"] == _target(cfg) for r in records)
        other = [] if ours else [r for r in records if r["type"] in ("A", "AAAA", "CNAME")]
        clashes += [{"host": host, "type": r["type"], "content": r["content"]} for r in other]
        plan.append((host, zone, None if ours else other))
    if clashes and not replace:
        shown = "; ".join(f"{c['host']} → {c['type']} {c['content']}" for c in clashes)
        raise Conflict(f"These names already point somewhere else at Cloudflare: {shown}. Replace them with this app? "
                       "Whatever they point to now stops being reachable at that name.",
                       extra={"code": "dns_conflict", "records": clashes})

    for host, zone, other in plan:
        if other is None:
            continue  # already points at the tunnel
        for r in other:
            await cf("DELETE", f"/zones/{zone['id']}/dns_records/{r['id']}")
        await cf("POST", f"/zones/{zone['id']}/dns_records", body={
            "type": "CNAME", "name": host, "content": _target(cfg), "proxied": True, "ttl": 1,
            "comment": f"phone-server: {name}"[:100],
        })
    await sync(override={name: new})
    db.update_app(name, domains=new)

    problems = await _unpoint(removed, zone_list, cfg)
    message = "Saved. " + ("Your domains point at this app." if new else "This app has no public domain now.")
    if problems:
        message += f" Couldn't remove the old DNS records for {', '.join(problems)}; delete them at Cloudflare."
    return message


async def _unpoint(hosts: list[str], zone_list: list[dict], cfg: dict) -> list[str]:
    """Delete our DNS records for these hosts. Returns the hosts that failed."""
    failed = []
    for host in hosts:
        zone = zone_for(host, zone_list)
        if not zone:
            continue
        try:
            records = (await cf("GET", f"/zones/{zone['id']}/dns_records", query={"name": host, "type": "CNAME"}))["result"]
            for r in records:
                if r["content"] == _target(cfg):
                    await cf("DELETE", f"/zones/{zone['id']}/dns_records/{r['id']}")
        except ApiError:
            failed.append(host)
    return failed


async def forget_app(app: dict) -> str | None:
    """Before an app is deleted: remove its DNS records and its routes. Returns a warning, if any."""
    cfg = load()
    if not cfg or not app["domains"]:
        return None
    try:
        await sync(override={app["name"]: []})
        failed = await _unpoint(app["domains"], await zones(force=True), cfg)
    except ApiError as e:
        return f"Couldn't remove its domains at Cloudflare: {e}"
    return f"Couldn't remove the DNS records for {', '.join(failed)}." if failed else None


async def sync(override: dict[str, list[str]] | None = None) -> None:
    """Send the tunnel its routes: each app domain → that app's port. Everything else → 404."""
    cfg = load()
    if not cfg:
        return
    override = override or {}
    ingress = []
    for app in db.list_apps():
        for host in override.get(app["name"], app["domains"]):
            ingress.append({"hostname": host, "service": f"http://127.0.0.1:{app['port']}"})
    ingress.append({"service": "http_status:404"})
    await cf("PUT", f"/accounts/{cfg['account_id']}/cfd_tunnel/{cfg['tunnel_id']}/configurations",
             body={"config": {"ingress": ingress}})


async def domain_info(app: dict) -> dict:
    cfg = load()
    out = {"connected": bool(cfg), "domains": [{"host": d} for d in app["domains"]]}
    if not cfg or not app["domains"]:
        return out
    try:
        zone_list = await zones()
    except ApiError as e:
        out["error"] = str(e)
        return out
    for d in out["domains"]:
        zone = zone_for(d["host"], zone_list)
        d["zone"] = zone and zone["name"]
        d["zone_status"] = zone and zone["status"]
        d["name_servers"] = zone["name_servers"] if zone and zone["status"] != "active" else []
    return out


# ---------- connecting ----------

async def _start_process(run_token: str) -> None:
    spec = {"apps": [{
        "name": PROCESS,
        "script": CLOUDFLARED,
        "args": ["tunnel", "--no-autoupdate", "run"],
        "interpreter": "none",
        "env": clean_env({"TUNNEL_TOKEN": run_token}),  # not on the command line, where ps would show it
        "out_file": str(LOG_FILE),
        "error_file": str(LOG_FILE),
        "merge_logs": True,
        "autorestart": True,
        "exp_backoff_restart_delay": 2000,  # e.g. no network yet after a reboot
        "max_restarts": 1000,
        "kill_timeout": 10000,
    }]}
    _write_private(ECO_FILE, spec)
    await pm2.delete(PROCESS)
    await pm2.start(ECO_FILE)
    await pm2.save()


async def connect(api_token) -> str:
    token = api_token.strip() if isinstance(api_token, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token):
        raise Invalid(f"That doesn't look like a Cloudflare API token. {TOKEN_HELP}")
    if not Path(CLOUDFLARED).exists():
        raise Conflict("cloudflared isn't installed on the phone. Run: pkg install cloudflared")
    accounts = (await cf("GET", "/accounts", token=token))["result"]
    if not accounts:
        # Listing accounts needs Account Settings → Read, which the token doesn't need otherwise.
        # Every zone names its account, so take it from there.
        site_list = (await cf("GET", "/zones", token=token, query={"per_page": 50}))["result"]
        seen: dict[str, dict] = {}
        for z in site_list:
            acc = z.get("account") or {}
            if acc.get("id"):
                seen.setdefault(acc["id"], {"id": acc["id"], "name": acc.get("name") or ""})
        accounts = list(seen.values())
    if not accounts:
        raise Invalid("The token can't see your Cloudflare account or any site in it. Add your domain at Cloudflare "
                      f"first, and check the token's permissions. {TOKEN_HELP}")
    account = accounts[0]
    base = f"/accounts/{account['id']}/cfd_tunnel"
    existing = (await cf("GET", base, token=token, query={"name": TUNNEL_NAME, "is_deleted": "false"}))["result"]
    # Reuse the phone's tunnel after a reconnect, so DNS records made earlier keep working.
    tunnel = next((t for t in existing if t.get("remote_config")), None)
    if not tunnel:
        name = TUNNEL_NAME if not existing else f"{TUNNEL_NAME}-{int(time.time())}"
        tunnel = (await cf("POST", base, token=token, body={"name": name, "config_src": "cloudflare"}))["result"]
    run_token = (await cf("GET", f"{base}/{tunnel['id']}/token", token=token))["result"]
    _write_private(CONFIG_FILE, {
        "api_token": token, "account_id": account["id"], "account_name": account.get("name") or "",
        "tunnel_id": tunnel["id"], "tunnel_name": tunnel["name"], "connected_at": time.time(),
    })
    await _start_process(run_token)
    await sync()
    try:
        found = await zones(force=True)
    except ApiError:
        found = []
    if not found:
        return ("Connected, but the token can't see any sites. Add your domain at Cloudflare, and make sure the "
                "token has Zone → DNS → Edit and Zone → Zone → Read for all zones.")
    return f"Connected to Cloudflare ({account.get('name') or 'your account'})."


async def disconnect() -> str:
    await pm2.delete(PROCESS)
    await pm2.save()
    for f in (ECO_FILE, CONFIG_FILE):
        f.unlink(missing_ok=True)
    return ("Disconnected. Apps' domains stop working until you connect again; the DNS records and the tunnel "
            "stay in your Cloudflare account.")


async def status() -> dict:
    cfg = load()
    out: dict = {"installed": Path(CLOUDFLARED).exists(), "connected": bool(cfg)}
    try:
        out["process"] = (await pm2.processes()).get(PROCESS)
    except pm2.PM2Error:
        out["process"] = None
    if not cfg:
        return out
    out.update(account=cfg.get("account_name"), tunnel=cfg.get("tunnel_name"))
    try:
        t = (await cf("GET", f"/accounts/{cfg['account_id']}/cfd_tunnel/{cfg['tunnel_id']}"))["result"]
        out["tunnel_status"] = t.get("status")  # healthy, degraded, down or inactive
        out["zones"] = await zones(force=True)
    except ApiError as e:
        out["error"] = str(e)
    used = {d: a["name"] for a in db.list_apps() for d in a["domains"]}
    out["domains"] = [{"host": d, "app": n} for d, n in sorted(used.items())]
    return out
