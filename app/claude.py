"""Talking to Claude, through Anthropic's own SDK.

Carmen used to run on Groq's OpenAI-compatible endpoint, which needed no client
library — one POST with messages and tools was the whole protocol. Anthropic's
API is a different shape and has a real Python SDK, so this uses it: typed
errors worth catching separately, retries and timeouts already thought about,
and a tool-use surface that will not drift out from under this file.

That makes `anthropic` the fourth package this app installs. It is pure Python
with no compiler in the chain, which is the bar the other three had to clear.

The key lives beside the database, never in it: the nightly backup uploads the
database, and a key inside the thing that gets uploaded is a key you have
published.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

# Opus 5 unless somebody chooses otherwise on Carmen's tab.
DEFAULT_MODEL = "claude-opus-5"

# Room for the thinking Claude does on its way to an answer as well as the
# answer itself; thinking tokens are counted here too, and a tool loop that
# runs out mid-sentence has to start again.
MAX_TOKENS = 16000

# How hard to think. `high` is the API's own default; `medium` and `low` are
# there for somebody who would rather have a quicker, cheaper reply on a small
# project than a thorough one.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "high"

TIMEOUT = 180.0
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").strip()


class ClaudeError(Exception):
    """Anything the API refused, in words worth putting on a screen."""


def configured(settings: Mapping[str, Any]) -> bool:
    return bool(str(settings.get("key") or settings.get("anthropic_key") or "").strip())


def settings_from_env(env: Mapping[str, str]) -> dict[str, str]:
    return {
        "anthropic_key": env.get("ANTHROPIC_API_KEY", "").strip(),
        "anthropic_model": env.get("ANTHROPIC_MODEL", "").strip(),
    }


def client(key: str):
    """A client for this key. Built per call — it is cheap, and a long-lived one
    would outlive the key being changed on the settings page."""
    import anthropic

    made: dict[str, Any] = {"api_key": key, "timeout": TIMEOUT, "max_retries": 2}
    if BASE_URL:
        # Pointed elsewhere for the browser test, which drives the whole feature
        # against a stand-in rather than a paid account.
        made["base_url"] = BASE_URL
    return anthropic.Anthropic(**made)


def _why(exc: Exception) -> str:
    """The failure, said in words somebody can act on.

    The 403 is the one worth care. A 403 from Anthropic is Anthropic refusing
    the key; a 403 from a host's own outbound proxy looks identical in a log and
    needs a completely different fix, and it is the one that actually happens.
    """
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return ("Anthropic did not accept that API key (401). Check it at "
                "console.anthropic.com, or paste a new one on Carmen's tab.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        said = getattr(exc, "message", "") or ""
        if said:
            return (f"Anthropic refused the request (403): {said} — that is the key or "
                    f"the account, not the network.")
        return ("Forbidden (403), and Anthropic said nothing — which means the request "
                "never reached them. Something between this server and the internet "
                "refused it. On PythonAnywhere's free plan every outbound request goes "
                "through a proxy that only allows listed sites, and api.anthropic.com "
                "is not one of them: Carmen needs a paid plan there, or a host without "
                "that restriction. Press “Test the connection” on her tab to see which "
                "it is.")
    if isinstance(exc, anthropic.NotFoundError):
        return (f"Anthropic has no such model (404). Pick another on Carmen's tab. "
                f"({getattr(exc, 'message', '')})")
    if isinstance(exc, anthropic.RateLimitError):
        return ("Rate limited (429) — too many requests, or the account is out of "
                "credit. Wait a moment and ask again.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ("Could not reach api.anthropic.com. On a host that only allows listed "
                "sites, it has to be one of them — on PythonAnywhere's free plan it is "
                "not, and Carmen cannot work there.")
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic said {exc.status_code}: {getattr(exc, 'message', '')}"
    return f"That did not work: {exc}"


def models(key: str) -> list[str]:
    """Which models this account can reach, read from the API itself.

    Not written down here, so the list is what is really available today rather
    than what was true when this was written.
    """
    import anthropic

    try:
        return sorted(model.id for model in client(key).models.list(limit=100))
    except anthropic.AnthropicError as exc:
        raise ClaudeError(_why(exc)) from exc


def chat(key: str, system: str, messages: Sequence[Mapping[str, Any]],
         tools: Sequence[Mapping[str, Any]] | None = None,
         model: str = "", effort: str = DEFAULT_EFFORT) -> Any:
    """One turn: the conversation so far, and what Claude says next.

    The answer is either words for the reader or one or more requests to call a
    tool. The caller runs them and asks again with the results.
    """
    import anthropic

    body: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": list(messages),
        # Adaptive: Claude decides how much to think, which is the right setting
        # for work that is sometimes "what is late" and sometimes "read these
        # four paragraphs and turn them into a numbered register".
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort if effort in EFFORTS else DEFAULT_EFFORT},
    }
    if tools:
        body["tools"] = list(tools)

    try:
        return client(key).messages.create(**body)
    except anthropic.AnthropicError as exc:
        raise ClaudeError(_why(exc)) from exc


def said(answer: Any) -> str:
    """The words out of an answer, without the thinking or the tool calls."""
    parts = [block.text for block in getattr(answer, "content", [])
             if getattr(block, "type", "") == "text"]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def tool_calls(answer: Any) -> list[dict[str, Any]]:
    """What it wants run, if anything.

    The arguments are passed on as they arrived rather than coerced: whether
    they are an object at all is the caller's check to make, and doing it here
    would turn a bad call into an exception instead of something the model can
    be told about and correct.
    """
    return [
        {"id": block.id, "name": block.name, "input": block.input}
        for block in getattr(answer, "content", [])
        if getattr(block, "type", "") == "tool_use"
    ]


def refused(answer: Any) -> str:
    """Why it declined, when it declined. Empty otherwise."""
    if getattr(answer, "stop_reason", "") != "refusal":
        return ""
    details = getattr(answer, "stop_details", None)
    reason = getattr(details, "explanation", "") or getattr(details, "category", "") or ""
    return (f"Claude declined to answer that ({reason})." if reason
            else "Claude declined to answer that.")


def diagnose(key: str) -> dict[str, Any]:
    """What is actually wrong, when nothing works.

    Three questions in order, because the answers to the later ones are
    meaningless if an earlier one failed: can this machine open a connection to
    Anthropic at all; does the key work; does a real request come back. A 403
    from a host's own proxy and a 403 from Anthropic look identical in a log and
    need completely different fixes, so they are told apart here rather than
    left for somebody to guess at.
    """
    import socket
    import ssl
    import urllib.parse

    found: dict[str, Any] = {"reachable": False, "key_works": False, "detail": "",
                             "models": 0}

    where = urllib.parse.urlparse(BASE_URL or "https://api.anthropic.com")
    host = where.hostname or "api.anthropic.com"
    port = where.port or (443 if where.scheme != "http" else 80)
    try:
        with socket.create_connection((host, port), timeout=10) as raw:
            if where.scheme != "http":
                # A TLS handshake, not just a socket: a proxy that accepts the
                # connection and then refuses the site fails here, which is
                # exactly the case worth telling apart.
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host):
                    pass
            found["reachable"] = True
    except OSError as exc:
        found["detail"] = (
            f"This server cannot open a connection to {host} ({exc}). That is the "
            f"host's network, not Anthropic and not the key — on PythonAnywhere's "
            f"free plan only allowlisted sites can be reached, and api.anthropic.com "
            f"is not among them.")
        return found

    if not str(key or "").strip():
        found["detail"] = "There is no API key saved yet."
        return found

    try:
        found["models"] = len(models(key))
        found["key_works"] = True
        found["detail"] = f"Connected. The key can reach {found['models']} models."
    except ClaudeError as exc:
        found["detail"] = str(exc)
    return found
