"""Talking to PM2.

Starting the pm2 CLI costs 5–15 seconds on a phone (Node has to load all of PM2),
so calls go through agent/pm2-agent.js, which keeps PM2 loaded and answers over
a Unix socket in milliseconds. If the agent isn't up (it takes a while to start
after a reboot), the slow CLI is used instead.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path

from .config import DATA, PM2, clean_env

AGENT_SOCK = DATA / "pm2-agent.sock"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class PM2Error(Exception):
    pass


class _AgentUnavailable(Exception):
    pass


async def _agent(op: str, timeout: float = 60, **params) -> object:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(AGENT_SOCK)), 2)
    except (OSError, TimeoutError) as e:
        raise _AgentUnavailable(str(e)) from None
    try:
        writer.write((json.dumps({"op": op, **params}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
    except TimeoutError:
        raise PM2Error(f"PM2 didn't answer within {timeout:.0f} seconds") from None
    except OSError as e:
        raise _AgentUnavailable(str(e)) from None
    finally:
        writer.close()
    if not line:
        raise _AgentUnavailable("agent closed the connection")
    reply = json.loads(line)
    if not reply.get("ok"):
        raise PM2Error(reply.get("error") or f"pm2 {op} failed")
    return reply.get("result")


async def run(*args: str, timeout: float = 90) -> str:
    """The pm2 CLI. Slow; only a fallback."""
    proc = await asyncio.create_subprocess_exec(
        PM2, *args, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=clean_env({"FORCE_COLOR": "0"}),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise PM2Error(f"pm2 {args[0]} took longer than {timeout:.0f} seconds") from None
    text = _ANSI.sub("", out.decode(errors="replace"))
    if proc.returncode != 0:
        detail = _ANSI.sub("", err.decode(errors="replace")).strip() or text.strip()
        raise PM2Error(detail[-600:] or f"pm2 {args[0]} failed")
    return text


async def _do(op: str, cli: list[str], **params) -> object:
    try:
        return await _agent(op, **params)
    except _AgentUnavailable:
        return await run(*cli)


# Shared for a moment so several browser tabs polling at once cost one call.
_cache: tuple[float, dict[str, dict]] = (0.0, {})
_lock = asyncio.Lock()


async def processes(max_age: float = 2.0) -> dict[str, dict]:
    global _cache
    async with _lock:
        if time.monotonic() - _cache[0] < max_age:
            return _cache[1]
        try:
            data = await _agent("list", timeout=30)
        except _AgentUnavailable:
            out = await run("jlist")
            start = out.find("[")
            data = json.loads(out[start:]) if start >= 0 else []
        procs = {p["name"]: _info(p) for p in data if p.get("name")}
        _cache = (time.monotonic(), procs)
        return procs


def invalidate() -> None:
    global _cache
    _cache = (0.0, _cache[1])


def _info(p: dict) -> dict:
    env = p.get("pm2_env") or {}
    monit = p.get("monit") or {}
    started = env.get("pm_uptime")
    return {
        "status": env.get("status") or "unknown",
        "pid": p.get("pid") or None,
        "cpu": monit.get("cpu", 0),
        "memory": monit.get("memory", 0),
        "started_at": started / 1000 if started else None,
        "restarts": env.get("restart_time", 0),
    }


async def start(file: Path) -> None:
    await _do("start", ["start", str(file)], file=str(file))
    invalidate()


async def stop(name: str) -> None:
    await _do("stop", ["stop", name], name=name)
    invalidate()


async def restart(name: str) -> None:
    await _do("restart", ["restart", name], name=name)
    invalidate()


async def delete(name: str) -> None:
    try:
        await _do("delete", ["delete", name], name=name)
    except PM2Error as e:
        if "not found" not in str(e).lower():
            raise
    invalidate()


async def save() -> None:
    """Remember the process list so `pm2 resurrect` brings it back after a reboot."""
    await _do("save", ["save", "--force"])
