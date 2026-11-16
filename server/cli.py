"""Command line tools, run on the phone:

    cd ~/phone-server && .venv/bin/python -m server.cli set-password
    cd ~/phone-server && .venv/bin/python -m server.cli deploy <app>
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from . import auth
from .config import ensure_dirs


def deploy_app(name: str) -> int:
    """Run a deploy in this process and stream its log. It shows up in the dashboard like any other."""
    from . import db, deploy

    if not db.get_app(name):
        print(f"There's no app called {name}.", file=sys.stderr)
        return 1
    if db.active_deployment(name):
        print("A deploy is already running for this app.", file=sys.stderr)
        return 1

    async def run() -> int:
        dep = db.create_deployment(name, "cli")
        task = asyncio.create_task(deploy._deploy_task(dep["id"], name))
        log_path = deploy.deploy_log_path(name, dep["id"])
        offset = 0
        while True:
            finished = task.done()
            if log_path.exists():
                with log_path.open("rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                offset += len(chunk)
                sys.stdout.write(chunk.decode(errors="replace"))
                sys.stdout.flush()
            if finished:
                break
            await asyncio.sleep(0.5)
        return 0 if db.get_deployment(dep["id"])["status"] == "success" else 1

    return asyncio.run(run())


# Runs inside psql so the password never appears on a command line.
CREATE_DB_SQL = r"""
\set ON_ERROR_STOP on
\set role '{role}'
\set pw '{password}'
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role') AS new_role \gset
\if :new_role
CREATE ROLE :"role" LOGIN PASSWORD :'pw';
\else
ALTER ROLE :"role" WITH LOGIN PASSWORD :'pw';
\endif
SELECT NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'role') AS new_db \gset
\if :new_db
CREATE DATABASE :"role" OWNER :"role";
\endif
"""


def create_db(name: str, replace: bool) -> int:
    """Give an app its own database on the phone's Postgres and set its DATABASE_URL."""
    import secrets
    import subprocess

    from . import db
    from .config import POSTGRES_PORT, clean_env

    app = db.get_app(name)
    if not app:
        print(f"There's no app called {name}.", file=sys.stderr)
        return 1
    if "DATABASE_URL" in app["env"] and not replace:
        print(f"{name} already has a DATABASE_URL. Use --replace to point it at a new local database.", file=sys.stderr)
        return 1
    role = name.replace("-", "_")
    password = secrets.token_urlsafe(24)  # letters, digits, - and _: safe inside the SQL and the URL
    # The superuser is trusted only over the local Unix socket (TCP always needs a password).
    result = subprocess.run(
        ["psql", "-X", "-q", "-U", "postgres", "-p", str(POSTGRES_PORT), "-d", "postgres"],
        input=CREATE_DB_SQL.format(role=role, password=password), text=True, capture_output=True,
        env=clean_env({"PGCONNECT_TIMEOUT": "10"}),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        print(f"Couldn't create the database: {detail}", file=sys.stderr)
        print("Is Postgres set up? Run: bash ~/phone-server/scripts/setup-postgres.sh", file=sys.stderr)
        return 1
    env = dict(app["env"])
    env["DATABASE_URL"] = f"postgresql://{role}:{password}@127.0.0.1:{POSTGRES_PORT}/{role}"
    db.update_app(name, env=env)
    print(f"Created database {role} and set DATABASE_URL for {name} (the password is only stored in the app's settings).")
    print("Redeploy the app, or press Save in its Settings, to use it.")
    return 0

MIN_LENGTH = 8


def set_password(from_stdin: bool) -> int:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New dashboard password: ")
        if getpass.getpass("Type it again: ") != password:
            print("The two passwords didn't match. Nothing changed.", file=sys.stderr)
            return 1
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters. Nothing changed.", file=sys.stderr)
        return 1
    auth.set_password(password)
    print("Password saved. Anyone already signed in has been signed out.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m server.cli", description="Phone Server tools")
    sub = parser.add_subparsers(dest="command", required=True)
    pw = sub.add_parser("set-password", help="set or change the dashboard password")
    pw.add_argument("--stdin", action="store_true", help="read the password from standard input")
    dp = sub.add_parser("deploy", help="deploy an app and print its log")
    dp.add_argument("name")
    cd = sub.add_parser("create-db", help="give an app its own Postgres database and set DATABASE_URL")
    cd.add_argument("name")
    cd.add_argument("--replace", action="store_true", help="replace an existing DATABASE_URL")
    args = parser.parse_args()
    ensure_dirs()
    if args.command == "set-password":
        return set_password(args.stdin)
    if args.command == "deploy":
        return deploy_app(args.name)
    if args.command == "create-db":
        return create_db(args.name, args.replace)
    return 1


if __name__ == "__main__":
    sys.exit(main())
