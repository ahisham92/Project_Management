"""Talking to Groq, with nothing but the standard library.

Groq serves an OpenAI-compatible API, which means one POST with a list of
messages and a list of tools, and an answer that is either words or a request
to call one of those tools. That is the whole protocol, so it needs no client
library — and this app has kept its install to three packages, which is worth
more than the convenience of a fourth.

The key never goes in the database. It sits beside it in the same file the
Drive credentials use, for the same reason: the nightly backup uploads the
database, and a key kept inside the thing that gets uploaded is a key you have
published.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Sequence

# Overridable so the browser test can point at a stand-in rather than at
# somebody's paid account, and so a host behind a gateway can be pointed at it.
BASE = os.environ.get("GROQ_BASE_URL", "").rstrip("/") or "https://api.groq.com/openai/v1"
CHAT_URL = f"{BASE}/chat/completions"
MODELS_URL = f"{BASE}/models"

# What the assistant runs on unless something else is chosen. The Backups-style
# settings card lists whatever the account can actually reach, read from the
# API itself, so a default that goes stale is one click from being fixed rather
# than a thing to edit in code.
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Long enough for a model to think through a few tool calls, short enough that
# a hung request does not hold a worker for the afternoon.
TIMEOUT = 90


class GroqError(Exception):
    """Anything Groq refused, in words worth putting on a screen."""


def configured(settings: Mapping[str, Any]) -> bool:
    return bool(str(settings.get("groq_key") or "").strip())


def settings_from_env(env: Mapping[str, str]) -> dict[str, str]:
    return {
        "groq_key": env.get("GROQ_API_KEY", "").strip(),
        "groq_model": env.get("GROQ_MODEL", "").strip(),
    }


def _send(url: str, key: str, body: Any = None, method: str = "GET") -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            raw = answer.read()
    except urllib.error.HTTPError as exc:
        raise GroqError(_why(exc)) from exc
    except urllib.error.URLError as exc:
        raise GroqError(
            f"Could not reach Groq ({exc.reason}). On a host that only allows listed "
            f"sites, api.groq.com has to be one of them — on PythonAnywhere's free "
            f"plan it is not, and the assistant cannot work there."
        ) from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _why(exc: urllib.error.HTTPError) -> str:
    """Groq's own reason, rather than a bare status code.

    Whether Groq said anything at all is the important part. A 403 carrying
    Groq's JSON is Groq refusing the key; a 403 carrying nothing came from
    something in between — which is a completely different fix, and the case
    that actually happens.
    """
    detail = ""
    try:
        said = json.loads(exc.read().decode("utf-8"))
    except Exception:                                # noqa: BLE001 - no body is itself the answer
        said = {}

    if isinstance(said.get("error"), dict):
        detail = said["error"].get("message") or said["error"].get("status") or ""
    elif said.get("error"):
        detail = str(said.get("error_description") or said["error"])

    if exc.code == 401:
        detail = (detail or "the key was not accepted") + \
            " — check the API key on Carmen's tab."
    elif exc.code == 403:
        detail = (
            detail + " — Groq refused the key itself. Check it is still active at "
            "console.groq.com/keys."
            if detail else
            "forbidden, and Groq said nothing — which means the request did not reach "
            "Groq. Something between this server and the internet refused it. On "
            "PythonAnywhere's free plan every outbound request goes through a proxy "
            "that only allows listed sites, and api.groq.com is not one of them: "
            "Carmen needs a paid plan there, or a host without that restriction. "
            "Press “Test the connection” on her tab to see which it is."
        )
    elif exc.code == 404 and "model" in detail.lower():
        detail += " — pick another model on Carmen's tab."
    elif exc.code == 429:
        detail = (detail or "too many requests") + \
            " — Groq's free tier has a rate limit; wait a moment and ask again."
    return f"Groq said {exc.code}: {detail}" if detail else f"Groq said {exc.code}"


def models(key: str) -> list[str]:
    """Which models this account can actually use, newest names first.

    Read from the API rather than written down here, so the list is what is
    really available today instead of what was true when this was written.
    """
    said = _send(MODELS_URL, key)
    found = [str(row.get("id") or "") for row in (said.get("data") or []) if row.get("id")]
    # Whisper and the guard models cannot hold a conversation; offering them
    # would only invite a confusing failure.
    talking = [name for name in found
               if not any(word in name.lower() for word in ("whisper", "guard", "tts", "embed"))]
    return sorted(talking)


def chat(key: str, messages: Sequence[Mapping[str, Any]],
         tools: Sequence[Mapping[str, Any]] | None = None,
         model: str = "", temperature: float = 0.2,
         max_tokens: int = 2000) -> dict[str, Any]:
    """One turn: the conversation so far, and what the model says next.

    The answer is either words for the reader or a request to call one or more
    of the tools. The caller runs them and asks again with the results.
    """
    body: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": list(messages),
        # Low, because this is being asked to read a schedule and act on it, not
        # to write prose. A model inventing a date here is worse than useless.
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = list(tools)
        body["tool_choice"] = "auto"

    said = _send(CHAT_URL, key, body, "POST")
    choices = said.get("choices") or []
    if not choices:
        raise GroqError("Groq returned no answer at all")
    return dict(choices[0].get("message") or {})


def diagnose(key: str) -> dict[str, Any]:
    """What is actually wrong, when nothing works.

    Three questions in order, because the answers to the later ones are
    meaningless if an earlier one failed: can this machine open a socket to
    Groq at all; does the key work; does the chosen model answer. A 403 from a
    host's own proxy and a 403 from Groq look identical in a log and need
    completely different fixes, so they are told apart here rather than left
    for somebody to guess at.
    """
    import socket
    import ssl
    import urllib.parse

    found: dict[str, Any] = {"reachable": False, "key_works": False, "detail": "", "models": 0}

    host = urllib.parse.urlparse(BASE).hostname or "api.groq.com"
    port = urllib.parse.urlparse(BASE).port or 443
    try:
        with socket.create_connection((host, port), timeout=10) as raw:
            # A TLS handshake, not just a socket: a proxy that accepts the
            # connection and then refuses the site fails here, which is exactly
            # the case worth telling apart.
            with ssl.create_default_context().wrap_socket(raw, server_hostname=host):
                found["reachable"] = True
    except OSError as exc:
        found["detail"] = (
            f"This server cannot open a connection to {host} ({exc}). That is the "
            f"host's network, not Groq and not the key — on PythonAnywhere's free "
            f"plan only allowlisted sites can be reached, and api.groq.com is not "
            f"among them.")
        return found

    if not str(key or "").strip():
        found["detail"] = "There is no API key saved yet."
        return found

    try:
        found["models"] = len(models(key))
        found["key_works"] = True
        found["detail"] = f"Connected. The key can reach {found['models']} models."
    except GroqError as exc:
        found["detail"] = str(exc)
    return found


def usage_of(said: Mapping[str, Any]) -> dict[str, int]:
    used = said.get("usage") or {}
    return {
        "prompt": int(used.get("prompt_tokens") or 0),
        "completion": int(used.get("completion_tokens") or 0),
        "total": int(used.get("total_tokens") or 0),
    }
