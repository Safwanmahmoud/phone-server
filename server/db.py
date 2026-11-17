"""SQLite storage for apps and their deployments (~/.phone-server/phone-server.db)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS app (
    name         TEXT PRIMARY KEY,
    repo_url     TEXT NOT NULL,
    branch       TEXT NOT NULL,
    start_cmd    TEXT NOT NULL DEFAULT '',
    detected_cmd TEXT NOT NULL DEFAULT '',
    port         INTEGER NOT NULL UNIQUE,
    env          TEXT NOT NULL DEFAULT '{}',
    domains      TEXT NOT NULL DEFAULT '[]',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deployment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    app         TEXT NOT NULL REFERENCES app(name) ON DELETE CASCADE,
    status      TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'failed')),
    trigger     TEXT NOT NULL,
    commit_sha  TEXT,
    commit_msg  TEXT,
    error       TEXT,
    warning     TEXT,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS deployment_app_idx ON deployment (app, id DESC);
"""

APP_COLUMNS = {"repo_url", "branch", "start_cmd", "detected_cmd", "port", "env", "domains"}
JSON_COLUMNS = ("env", "domains")
DEPLOYMENT_COLUMNS = {"status", "commit_sha", "commit_msg", "error", "warning", "started_at", "finished_at"}


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:  # commit on success, roll back on error
            yield conn
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(app)")}
        if "domains" not in columns:  # added after the first release
            conn.execute("ALTER TABLE app ADD COLUMN domains TEXT NOT NULL DEFAULT '[]'")
    # A deploy can't survive a dashboard restart, so close out any that were cut off.
    with connect() as conn:
        conn.execute(
            "UPDATE deployment SET status = 'failed', error = ?, finished_at = ? WHERE status IN ('queued', 'running')",
            ("Interrupted: the dashboard restarted during this deploy.", time.time()),
        )


def _app(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    app = dict(row)
    app["env"] = json.loads(app["env"] or "{}")
    app["domains"] = json.loads(app["domains"] or "[]")
    return app


def list_apps() -> list[dict]:
    with connect() as conn:
        return [_app(r) for r in conn.execute("SELECT * FROM app ORDER BY name")]


def get_app(name: str) -> dict | None:
    with connect() as conn:
        return _app(conn.execute("SELECT * FROM app WHERE name = ?", (name,)).fetchone())


def insert_app(*, name: str, repo_url: str, branch: str, start_cmd: str, port: int, env: dict) -> None:
    now = time.time()
    with connect() as conn:
        conn.execute(
            "INSERT INTO app (name, repo_url, branch, start_cmd, port, env, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, repo_url, branch, start_cmd, port, json.dumps(env), now, now),
        )


def update_app(name: str, **fields) -> None:
    unknown = set(fields) - APP_COLUMNS
    if unknown:
        raise ValueError(f"unknown app columns: {unknown}")
    if not fields:
        return
    for col in JSON_COLUMNS:
        if col in fields:
            fields[col] = json.dumps(fields[col])
    sets = ", ".join(f"{col} = ?" for col in fields)
    with connect() as conn:
        conn.execute(f"UPDATE app SET {sets}, updated_at = ? WHERE name = ?", (*fields.values(), time.time(), name))


def delete_app(name: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM app WHERE name = ?", (name,))


def domain_owner(host: str) -> str | None:
    """The app that already uses this hostname, if any."""
    return next((a["name"] for a in list_apps() if host in a["domains"]), None)


def used_ports(exclude: str | None = None) -> set[int]:
    with connect() as conn:
        return {r[0] for r in conn.execute("SELECT port FROM app WHERE name != ?", (exclude or "",))}


def create_deployment(app: str, trigger: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO deployment (app, status, trigger, created_at) VALUES (?, 'queued', ?, ?)",
            (app, trigger, time.time()),
        )
        return dict(conn.execute("SELECT * FROM deployment WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_deployment(dep_id: int, **fields) -> None:
    unknown = set(fields) - DEPLOYMENT_COLUMNS
    if unknown:
        raise ValueError(f"unknown deployment columns: {unknown}")
    if not fields:
        return
    sets = ", ".join(f"{col} = ?" for col in fields)
    with connect() as conn:
        conn.execute(f"UPDATE deployment SET {sets} WHERE id = ?", (*fields.values(), dep_id))


def get_deployment(dep_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM deployment WHERE id = ?", (dep_id,)).fetchone()
        return dict(row) if row else None


def list_deployments(app: str, limit: int = 30) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM deployment WHERE app = ? ORDER BY id DESC LIMIT ?", (app, limit))
        return [dict(r) for r in rows]


def latest_deployments() -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT d.* FROM deployment d"
            " JOIN (SELECT app, MAX(id) AS id FROM deployment GROUP BY app) m ON m.id = d.id"
        )
        return {r["app"]: dict(r) for r in rows}


def active_deployment(app: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM deployment WHERE app = ? AND status IN ('queued', 'running') ORDER BY id DESC LIMIT 1",
            (app,),
        ).fetchone()
        return dict(row) if row else None


def active_apps() -> set[str]:
    with connect() as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT app FROM deployment WHERE status IN ('queued', 'running')")}
