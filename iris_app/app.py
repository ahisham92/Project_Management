"""Iris: the line between any AI tool and the person it works for.

Two kinds of caller, two halves of the API:

* **Tools** (Sketch ProMax on a PC, and whatever comes next) call ``/api/tool/...``
  with the token they were given when a phone accepted them. They send updates
  and questions, and read back answers, commands and messages. They only ever
  call out, so a PC behind a company proxy needs nothing opened.
* **The phone** opens the Iris pages as the signed-in account and calls
  ``/api/me/...``. Who is signed in is decided by the site Iris is mounted in,
  which puts the account into the request under ``SITE_KEY``; Iris has no
  sign-in of its own.

Every message body is encrypted by the sender and decrypted by the receiver
with a key that travels from the PC to the phone inside the pairing QR code,
after the ``#`` of the link, so it never reaches this server.
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from . import push
from .store import Store, StoreError

#: Where a site that mounts Iris says who is asking: {"id", "name", "login", "logout", "home"}.
SITE_KEY = "iris.site"

#: The only pages a browser may open without being signed in: the pairing
#: landing page keeps the key from the QR code before the sign-in can lose it.
#: The service worker and manifest must load for the home-screen app to work.
PUBLIC_PAGES = frozenset({"/pair", "/sw.js", "/manifest.webmanifest"})


def is_public(path: str) -> bool:
    """Whether a path is answered without the site's sign-in (tools carry their own token)."""
    return path in PUBLIC_PAGES or path.startswith("/api/tool/") or path.startswith("/static/")


def create_app(store: Store | None = None) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.store = store or Store()
    notify = push.notify
    app.notify = lambda account, payload: notify(app.store, account, payload)

    @app.errorhandler(StoreError)
    def _store_error(exc: StoreError):
        return jsonify(error=exc.message), exc.status

    def account() -> dict[str, Any]:
        site = request.environ.get(SITE_KEY)
        if site is None and os.environ.get("IRIS_DEV_ACCOUNT"):
            site = {"id": os.environ["IRIS_DEV_ACCOUNT"], "name": "Developer"}
        if not site:
            raise StoreError(401, "Sign in to use Iris.")
        return site

    def body() -> dict[str, Any]:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise StoreError(400, "Send JSON.")
        return data

    def tool():
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        return app.store.tool_by_token(token)

    # ---- pages -------------------------------------------------------------

    @app.get("/")
    def home():
        who = account()
        return render_template("app.html", who=who, vapid=push.public_key())

    @app.get("/pair")
    def pair_page():
        return render_template("pair.html")

    @app.get("/sw.js")
    def service_worker():
        reply = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript")
        reply.headers["Service-Worker-Allowed"] = request.script_root + "/"
        reply.headers["Cache-Control"] = "no-cache"
        return reply

    @app.get("/manifest.webmanifest")
    def manifest():
        root = request.script_root
        return jsonify({
            "name": "Iris", "short_name": "Iris",
            "description": "Your AI tools, on your phone.",
            "start_url": root + "/", "scope": root + "/", "display": "standalone",
            "background_color": "#101B2D", "theme_color": "#101B2D",
            "icons": [
                {"src": root + "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": root + "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": root + "/static/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        })

    # ---- the tool's half -----------------------------------------------------

    @app.post("/api/tool/pair")
    def tool_pair():
        data = body()
        return jsonify(app.store.start_pairing(data.get("name", ""), data.get("machine", ""),
                                               data.get("commands") or []))

    @app.get("/api/tool/pair/<int:pair_id>")
    def tool_pair_status(pair_id: int):
        return jsonify(app.store.pairing_status(pair_id, request.headers.get("X-Pair-Secret", "")))

    @app.get("/api/tool/me")
    def tool_me():
        row = tool()
        return jsonify(id=row["id"], name=row["name"], machine=row["machine"])

    @app.post("/api/tool/messages")
    def tool_send():
        row = tool()
        data = body()
        kind = data.get("kind", "")
        sent = app.store.post(row["id"], "tool", kind, data.get("body", ""), data.get("reply_to"))
        if kind == "question" and row["notify"] in ("all", "questions") or kind == "update" and row["notify"] == "all":
            words = "has a question" if kind == "question" else "sent an update"
            app.notify(row["account"], {"title": row["name"], "body": f"{row['name']} {words}",
                                        "tool": row["id"], "message": sent["id"]})
        return jsonify(sent)

    @app.get("/api/tool/inbox")
    def tool_inbox():
        row = tool()
        return jsonify(messages=app.store.messages(row["id"], request.args.get("after", 0, type=int), side="phone"))

    @app.delete("/api/tool/me")
    def tool_leave():
        row = tool()
        app.store.disconnect(row["id"])
        return jsonify(ok=True)

    # ---- the phone's half ----------------------------------------------------

    @app.get("/api/me/tools")
    def my_tools():
        return jsonify(tools=app.store.tools(account()["id"]))

    @app.get("/api/me/pair/<code>")
    def my_pair_preview(code: str):
        account()
        return jsonify(app.store.describe_pairing(code))

    @app.post("/api/me/pair")
    def my_pair():
        return jsonify(app.store.accept_pairing(account()["id"], body().get("code", "")))

    @app.get("/api/me/tools/<int:tool_id>/messages")
    def my_messages(tool_id: int):
        app.store.tool_for(account()["id"], tool_id)
        after = request.args.get("after", type=int)
        if after is None:
            return jsonify(messages=app.store.recent(tool_id))
        return jsonify(messages=app.store.messages(tool_id, after))

    @app.post("/api/me/tools/<int:tool_id>/messages")
    def my_send(tool_id: int):
        app.store.tool_for(account()["id"], tool_id)
        data = body()
        return jsonify(app.store.post(tool_id, "phone", data.get("kind", ""), data.get("body", ""),
                                      data.get("reply_to")))

    @app.post("/api/me/tools/<int:tool_id>/notify")
    def my_notify(tool_id: int):
        app.store.set_notify(account()["id"], tool_id, body().get("notify", ""))
        return jsonify(ok=True)

    @app.delete("/api/me/tools/<int:tool_id>")
    def my_disconnect(tool_id: int):
        app.store.disconnect(tool_id, account()["id"])
        return jsonify(ok=True)

    @app.post("/api/me/phones")
    def my_phone():
        data = body()
        keys = data.get("keys") or {}
        app.store.add_phone(account()["id"], data.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", ""))
        return jsonify(ok=True)

    @app.post("/api/me/phones/test")
    def my_phone_test():
        sent = app.notify(account()["id"], {"title": "Iris", "body": "Notifications are working."})
        return jsonify(sent=sent)

    @app.after_request
    def _no_store(reply: Response):
        if request.path.startswith("/api/"):
            reply.headers["Cache-Control"] = "no-store"
        return reply

    return app
