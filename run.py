#!/usr/bin/env python3
"""Project Control — start the server or set up the database.

    python run.py                 start the server on http://localhost:8000
    python run.py --port 9000     start it on a different port
    python run.py seed            create the first account and load the demo project
    python run.py create-user     add an account from the command line
    python run.py init-db         create an empty database

On Windows use "py" in place of "python3"/"python" if that is how Python is
installed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import webbrowser
from threading import Timer


def _serve(args: argparse.Namespace) -> int:
    from app import create_app
    from app.db import database_path

    app = create_app()
    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"

    print(f"Project Control is running at {url}")
    print(f"Database: {database_path()}")
    print("Press Ctrl+C to stop.\n")

    if args.open:
        Timer(1.0, lambda: webbrowser.open(url)).start()

    if args.debug:
        app.run(host=args.host, port=args.port, debug=True)
    else:
        # Waitress is a production-quality pure-Python server, so the same
        # command works on a laptop and on a shared machine.
        from waitress import serve

        serve(app, host=args.host, port=args.port, threads=args.threads)
    return 0


def _seed(_args: argparse.Namespace) -> int:
    from app.seed import seed

    seed()
    return 0


def _init_db(_args: argparse.Namespace) -> int:
    from app.db import database_path, init_db

    init_db()
    print(f"Database ready at {database_path()}")
    return 0


def _create_user(args: argparse.Namespace) -> int:
    from app.auth import hash_password
    from app.db import connect, init_db

    init_db()
    email = (args.email or input("Email: ")).strip().lower()
    name = (args.name or input("Full name: ")).strip() or email.split("@")[0]
    password = args.password or getpass.getpass("Password (at least 8 characters): ")

    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 1

    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone():
            print(f"An account for {email} already exists.", file=sys.stderr)
            return 1
        first_user = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
        role = "admin" if (first_user or args.admin) else "user"
        with conn:
            conn.execute(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (email, name, hash_password(password), role),
            )
        print(f"Created {role} account for {email}")
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--threads", type=int, default=8, help="worker threads (default 8)")
    parser.add_argument("--debug", action="store_true", help="auto-reload for development")
    parser.add_argument("--open", action="store_true", help="open a browser once the server starts")
    parser.set_defaults(func=_serve)

    sub = parser.add_subparsers()
    sub.add_parser("serve", help="start the web server").set_defaults(func=_serve)
    sub.add_parser("seed", help="create the first account and load the demo project").set_defaults(func=_seed)
    sub.add_parser("init-db", help="create an empty database").set_defaults(func=_init_db)

    create = sub.add_parser("create-user", help="add an account")
    create.add_argument("--email")
    create.add_argument("--name")
    create.add_argument("--password")
    create.add_argument("--admin", action="store_true", help="make this account an administrator")
    create.set_defaults(func=_create_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
