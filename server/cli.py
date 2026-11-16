"""Command line tools, run on the phone:

    cd ~/phone-server && .venv/bin/python -m server.cli set-password
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth
from .config import ensure_dirs

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
    args = parser.parse_args()
    ensure_dirs()
    if args.command == "set-password":
        return set_password(args.stdin)
    return 1


if __name__ == "__main__":
    sys.exit(main())
