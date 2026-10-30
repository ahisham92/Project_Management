"""Connect a Python tool to Iris in a few lines.

    from iris_client import Iris

    iris = Iris.load("my-tool.json", site="https://you.pythonanywhere.com/iris")
    if not iris.connected:
        link = iris.start_pairing("My tool", machine="PC-01", commands=["Stop"])
        print("Scan this with your phone:", link)        # show it as a QR code
        iris.wait_for_phone()                           # saves the token and key
    q = iris.ask("4 lengths or 3?", options=["4", "3"], assumed="4")
    iris.update("15 jobs done, 30 left")
    for m in iris.inbox():                              # answers, commands, messages
        print(m["kind"], m["value"])

Needs ``cryptography`` (pip install cryptography). The key is made here and
travels to the phone inside the link, after the ``#``, so the site never has it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(key: bytes, value: Any) -> str:
    """Encrypt ``value`` (anything JSON) the way every Iris client does."""
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    plain = padder.update(json.dumps(value).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(key[:32]), modes.CBC(iv)).encryptor()
    signed = iv + enc.update(plain) + enc.finalize()
    return "v1." + _b64u(signed + hmac.new(key[32:], signed, hashlib.sha256).digest())


def open_sealed(key: bytes, sealed: str) -> Any:
    if not sealed.startswith("v1."):
        raise ValueError("Not an Iris message.")
    raw = _unb64u(sealed[3:])
    signed, tag = raw[:-32], raw[-32:]
    if not hmac.compare_digest(tag, hmac.new(key[32:], signed, hashlib.sha256).digest()):
        raise ValueError("Message was changed or the key is wrong.")
    dec = Cipher(algorithms.AES(key[:32]), modes.CBC(signed[:16])).decryptor()
    padded = dec.update(signed[16:]) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return json.loads(unpadder.update(padded) + unpadder.finalize())


class IrisError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Iris:
    def __init__(self, site: str, state_file: str | Path, state: dict[str, Any] | None = None):
        self.site = site.rstrip("/")
        self.state_file = Path(state_file)
        self.state = state or {}

    @classmethod
    def load(cls, state_file: str | Path, site: str) -> "Iris":
        path = Path(state_file)
        state = json.loads(path.read_text()) if path.exists() else {}
        return cls(state.get("site") or site, path, state)

    @property
    def connected(self) -> bool:
        return bool(self.state.get("token") and self.state.get("key"))

    @property
    def key(self) -> bytes:
        return _unb64u(self.state["key"])

    def _save(self) -> None:
        self.state["site"] = self.site
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def _call(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.site + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.state.get("token"):
            req.add_header("Authorization", "Bearer " + self.state["token"])
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=20) as reply:
                return json.loads(reply.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read()).get("error", str(exc))
            except Exception:                           # noqa: BLE001
                message = str(exc)
            if exc.code == 401:
                self.state.pop("token", None)
                self._save()
            raise IrisError(exc.code, message) from None

    # ---- connecting ----------------------------------------------------------

    def start_pairing(self, name: str, machine: str | None = None, commands: list[str] | None = None) -> str:
        """Ask to be connected. Returns the link to show as a QR code."""
        self.state = {"key": _b64u(os.urandom(64))}
        got = self._call("POST", "/api/tool/pair", {"name": name, "machine": machine or socket.gethostname(),
                                                     "commands": commands or []})
        self.state.update(pair_id=got["pair_id"], pair_secret=got["secret"], code=got["code"])
        self._save()
        return f"{self.site}/pair?c={got['code']}#k={self.state['key']}"

    def check_pairing(self) -> str:
        """'waiting', 'expired' or 'connected' (and then the tool is ready)."""
        got = self._call("GET", f"/api/tool/pair/{self.state['pair_id']}",
                         headers={"X-Pair-Secret": self.state["pair_secret"]})
        if got["status"] == "connected":
            for k in ("pair_id", "pair_secret", "code"):
                self.state.pop(k, None)
            self.state.update(token=got["token"], tool_id=got["tool_id"], after=0)
            self._save()
        return got["status"]

    def wait_for_phone(self, every: float = 3, timeout: float = 600) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            status = self.check_pairing()
            if status != "waiting":
                return status == "connected"
            time.sleep(every)
        return False

    def disconnect(self) -> None:
        try:
            self._call("DELETE", "/api/tool/me")
        finally:
            self.state = {}
            self._save()

    # ---- talking -------------------------------------------------------------

    def send(self, kind: str, value: Any, reply_to: int | None = None) -> int:
        body = {"kind": kind, "body": seal(self.key, value)}
        if reply_to is not None:
            body["reply_to"] = reply_to
        return self._call("POST", "/api/tool/messages", body)["id"]

    def update(self, text: str) -> int:
        return self.send("update", {"text": text})

    def ask(self, text: str, options: list[str] | None = None, assumed: str | None = None,
            deadline: str | None = None) -> int:
        """Ask a question. Returns its id; the answer comes back through ``inbox``."""
        value: dict[str, Any] = {"text": text}
        if options:
            value["options"] = options
        if assumed:
            value["assumed"] = assumed
        if deadline:
            value["deadline"] = deadline
        return self.send("question", value)

    def settle(self, question_id: int, text: str) -> int:
        """Close a question on this side (for example, went with the assumption)."""
        return self.send("closed", {"text": text}, reply_to=question_id)

    def inbox(self) -> list[dict[str, Any]]:
        """New answers, commands and messages from the phone, decrypted, oldest first."""
        got = self._call("GET", f"/api/tool/inbox?after={self.state.get('after', 0)}")["messages"]
        out = []
        for m in got:
            try:
                m["value"] = open_sealed(self.key, m.pop("body"))
            except ValueError as exc:
                m["value"] = {"error": str(exc)}
            out.append(m)
            self.state["after"] = max(self.state.get("after", 0), m["id"])
        if got:
            self._save()
        return out
