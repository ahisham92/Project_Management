#!/usr/bin/env python3
"""Project Control — start the server or set up the database.

    python run.py                 start the server on http://localhost:8000
    python run.py --port 9000     start it on a different port
    python run.py seed            create the first account and load the demo project
    python run.py create-user     add an account from the command line
    python run.py init-db         create an empty database
    python run.py backup          back everything up and put it on Google Drive
    python run.py restore FILE    put a backup back
    python run.py drive-auth      connect a Google account, once

On Windows use "py" in place of "python3"/"python" if that is how Python is
installed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import webbrowser
from pathlib import Path
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


def _backup(args: argparse.Namespace) -> int:
    """Everything, in one file, on Google Drive — the nightly job."""
    from app import create_app
    from app.backup import readable
    from app.service import run_backup

    app = create_app()
    with app.app_context():
        result = run_backup(upload_to_drive=not args.local, note=args.note or "")

    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result["data"])
        print(f"Written to {target} ({readable(len(result['data']))})")

    counts = (result.get("manifest") or {}).get("counts", {})
    if counts:
        print(f"{counts.get('projects', 0)} project(s), {counts.get('tasks', 0)} deliverables, "
              f"{counts.get('meeting_items', 0)} minuted items")

    print(result.get("detail", ""))
    if result.get("link"):
        print(result["link"])
    return 0 if result["ok"] else 1


def _restore(args: argparse.Namespace) -> int:
    """Put a backup back over the live database."""
    from app import create_app
    from app.backup import RestoreError, read_manifest, restore
    from app.db import live_database

    source = Path(args.file)
    if not source.exists():
        print(f"No such file: {source}", file=sys.stderr)
        return 1

    data = source.read_bytes()
    try:
        manifest = read_manifest(data)
    except Exception as exc:                          # noqa: BLE001 - said plainly below
        print(f"That does not look like a backup: {exc}", file=sys.stderr)
        return 1

    with create_app().app_context():
        where = live_database()
    print(f"Backup taken {manifest.get('taken_at', 'at an unknown time')}")
    for project in manifest.get("projects", []):
        print(f"  {project.get('code', '')}  {project.get('name', '')}")
    counts = manifest.get("counts", {})
    if counts:
        print("  " + ", ".join(f"{name} {n}" for name, n in counts.items() if n))
    print(f"\nThis replaces {where}.")

    if not args.yes:
        if input("Type RESTORE to go ahead: ").strip() != "RESTORE":
            print("Nothing was changed.")
            return 1

    try:
        restore(data, where, keep_old=not args.no_keep)
    except RestoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Restored. The database that was there is beside it as "
          f"{Path(where).name}.replaced-… unless you said not to keep it.")
    return 0


def _drive_auth(args: argparse.Namespace) -> int:
    """Sign in to Google once and print the three values to keep.

    Run this on a machine with a browser. It listens on localhost for the one
    redirect Google makes, so nothing has to be copied out of a browser bar.
    """
    import http.server
    import threading
    import urllib.parse

    from app.drive import DriveError, consent_url, exchange

    client_id = (args.client_id or os.environ.get("GOOGLE_CLIENT_ID") or
                 input("Client ID: ")).strip()
    client_secret = (args.client_secret or os.environ.get("GOOGLE_CLIENT_SECRET") or
                     getpass.getpass("Client secret: ")).strip()
    if not client_id or not client_secret:
        print("Both a client ID and a client secret are needed.", file=sys.stderr)
        return 1

    caught: dict[str, str] = {}

    class Catcher(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                             # noqa: N802 - the name http.server wants
            asked = urllib.parse.urlparse(self.path)
            caught.update({k: v[0] for k, v in urllib.parse.parse_qs(asked.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            done = "code" in caught
            self.wfile.write(
                b"<h2>Done - close this tab and go back to the terminal.</h2>" if done
                else b"<h2>Google did not send a code. Try again.</h2>")

        def log_message(self, *_args):                # keep the terminal clean
            return

    server = http.server.HTTPServer(("127.0.0.1", args.port), Catcher)
    redirect = f"http://localhost:{server.server_port}/"
    url = consent_url(client_id, redirect)

    print("\nOpen this in a browser and sign in as the Google account whose Drive")
    print("the backups should go to:\n")
    print(f"  {url}\n")
    print(f"Waiting on {redirect} …")

    threading.Thread(target=server.handle_request, daemon=True).start()
    if args.open:
        webbrowser.open(url)
    server.socket.settimeout(300)
    for _ in range(3000):
        if caught:
            break
        import time

        time.sleep(0.1)

    if "code" not in caught:
        print(caught.get("error", "No code came back."), file=sys.stderr)
        return 1

    try:
        token = exchange(client_id, client_secret, caught["code"], redirect)
    except DriveError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("\nConnected. Set these three, and keep them out of the repository:\n")
    print(f'  GOOGLE_CLIENT_ID="{client_id}"')
    print(f'  GOOGLE_CLIENT_SECRET="{client_secret}"')
    print(f'  GOOGLE_REFRESH_TOKEN="{token["refresh_token"]}"')
    print("\nOptionally, to put the file in a particular folder — the id is the last")
    print("part of the folder's URL in Drive:\n")
    print('  GOOGLE_DRIVE_FOLDER_ID="…"')
    print("\nThen: python run.py backup")
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

    back = sub.add_parser("backup", help="back everything up and put it on Google Drive")
    back.add_argument("--local", action="store_true", help="take it but do not upload")
    back.add_argument("--out", help="also write the zip here")
    back.add_argument("--note", help="a line stored inside the backup")
    back.set_defaults(func=_backup)

    put = sub.add_parser("restore", help="put a backup back over the live database")
    put.add_argument("file", help="the backup zip")
    put.add_argument("--yes", action="store_true", help="do not ask first")
    put.add_argument("--no-keep", action="store_true",
                     help="do not keep the database being replaced")
    put.set_defaults(func=_restore)

    auth = sub.add_parser("drive-auth", help="connect a Google account, once")
    auth.add_argument("--client-id")
    auth.add_argument("--client-secret")
    auth.add_argument("--port", type=int, default=8765, help="the port to catch the redirect on")
    auth.add_argument("--open", action="store_true", help="open the browser for you")
    auth.set_defaults(func=_drive_auth)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
