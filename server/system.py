"""What the phone lets an app read about itself.

Android 8+ hides /proc/stat, /proc/loadavg and /proc/uptime from apps, so overall
CPU load and uptime aren't available. Per-core clock speed, memory, storage and
the thermal sensors are. Battery level needs the Termux:API app.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path

from .config import HOME, PREFIX, clean_env

STARTED = time.time()


def memory() -> dict:
    info: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                info[key] = int(parts[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return {
        "total": total,
        "available": available,
        "used": total - available,
        "swap_total": info.get("SwapTotal", 0),
        "swap_used": info.get("SwapTotal", 0) - info.get("SwapFree", 0),
    }


def storage() -> dict:
    st = os.statvfs(HOME)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total": total, "free": free, "used": total - free}


def cpu() -> dict:
    cores = []
    base = Path("/sys/devices/system/cpu")
    for d in sorted(base.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:])):
        try:
            cur = int((d / "cpufreq" / "scaling_cur_freq").read_text())
            top = int((d / "cpufreq" / "cpuinfo_max_freq").read_text())
        except (OSError, ValueError):
            continue  # core is offline
        cores.append({"cur_mhz": cur // 1000, "max_mhz": top // 1000})
    return {"count": os.cpu_count(), "cores": cores}


# Some sensors take seconds to read (on the OPPO A76, camera-therm and chg-skin-therm
# take 2–3 s each), so only the ones shown are read, and any that turn out slow are skipped.
_zones: dict[str, Path] | None = None
_slow_zones: set[str] = set()
SLOW_READ = 0.3
SKIN_ZONES = ("shell_back", "skin-therm", "skin-therm-usr", "quiet-therm-usr", "chg-skin-therm-usr")


def _zone_index() -> dict[str, Path]:
    global _zones
    if _zones is None:
        _zones = {}
        for z in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                _zones.setdefault((z / "type").read_text().strip(), z)
            except OSError:
                continue
    return _zones


def _read_zone(kind: str) -> float | None:
    path = _zone_index().get(kind)
    if path is None or kind in _slow_zones:
        return None
    started = time.monotonic()
    try:
        raw = int((path / "temp").read_text())
    except (OSError, ValueError):
        return None
    if time.monotonic() - started > SLOW_READ:
        _slow_zones.add(kind)
    value = raw / 1000 if abs(raw) >= 1000 else float(raw)
    return value if -20 < value < 150 else None  # some sensors report nonsense


def temperatures() -> dict:
    zones = _zone_index()
    cpu_kinds = [k for k in zones if k.startswith(("cpu-", "cpuss-")) and k.endswith("-usr") and "therm" not in k]
    if not cpu_kinds:
        cpu_kinds = [k for k in zones if "cpu" in k][:8]
    cpu_values = [v for k in cpu_kinds if (v := _read_zone(k)) is not None]
    skin = next((v for k in SKIN_ZONES if k in zones and (v := _read_zone(k)) is not None), None)
    return {"cpu": max(cpu_values) if cpu_values else None, "battery": _read_zone("battery"), "skin": skin}


def snapshot() -> dict:
    """Everything that reads files or runs getprop. Call it off the event loop."""
    return {"device": device(), "memory": memory(), "storage": storage(), "cpu": cpu(), "temperature": temperatures()}


_battery: dict = {"at": -1e9, "value": None}
_battery_lock = asyncio.Lock()


async def battery() -> dict:
    exe = shutil.which("termux-battery-status")
    if not exe:
        return {"available": False, "reason": "package"}
    async with _battery_lock:
        if time.monotonic() - _battery["at"] < 60:
            return _battery["value"]
        proc = await asyncio.create_subprocess_exec(exe, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, env=clean_env())
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 8)
            data = json.loads(out)
            value = {
                "available": True,
                "percent": data.get("percentage"),
                "status": data.get("status"),
                "plugged": data.get("plugged"),
                "temperature": data.get("temperature"),
            }
        except TimeoutError:  # hangs when the Termux:API app isn't installed
            proc.kill()
            await proc.wait()
            value = {"available": False, "reason": "app"}
        except (ValueError, OSError):
            value = {"available": False, "reason": "app"}
        _battery.update(at=time.monotonic(), value=value)
        return value


_device: dict | None = None


def device() -> dict:
    global _device
    if _device is None:
        def prop(key: str) -> str:
            try:
                return subprocess.run(["getprop", key], capture_output=True, text=True, timeout=3).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return ""
        market = next((v for v in (prop("ro.product.marketname"), prop("ro.vendor.oplus.market.name"),
                                   prop("ro.oppo.market.name")) if v), "")
        maker, model = prop("ro.product.manufacturer"), prop("ro.product.model")
        _device = {
            "name": market or " ".join(x for x in (maker, model) if x) or "Android phone",
            "model": model,
            "android": prop("ro.build.version.release"),
        }
    return _device


_versions: dict | None = None
_PACKAGES = {"python": "Python", "nodejs-lts": "Node.js", "git": "Git", "caddy": "Caddy", "ttyd": "ttyd"}


async def versions() -> dict:
    """Read from the package database: running `caddy version` or `pm2 --version` takes seconds here."""
    global _versions
    if _versions is None:
        found: dict[str, str] = {}
        try:
            proc = await asyncio.create_subprocess_exec(
                "dpkg-query", "-W", "-f", "${Package} ${Version}\n", *_PACKAGES,
                stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, env=clean_env(),
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 15)
            for line in out.decode(errors="replace").splitlines():
                pkg, _, version = line.partition(" ")
                if version:
                    found[pkg] = version
        except (OSError, TimeoutError):
            pass
        result = {label: found.get(pkg) for pkg, label in _PACKAGES.items()}
        try:
            result["PM2"] = json.loads((PREFIX / "lib/node_modules/pm2/package.json").read_text())["version"]
        except (OSError, ValueError, KeyError):
            result["PM2"] = None
        _versions = result
    return _versions
