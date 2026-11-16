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
    args = parser.parse_args()
    ensure_dirs()
    if args.command == "set-password":
        return set_password(args.stdin)
    if args.command == "deploy":
        return deploy_app(args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
