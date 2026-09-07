"""A stand-in for Anthropic's Messages API, so the browser test can drive Carmen.

Pointing a smoke test at a real paid API would make it slow, flaky and
expensive, and would test somebody else's uptime rather than this app. What is
worth checking is everything on this side of the wire: that a tool call is run
and fed back, that a change is staged rather than done, and that the page draws
the proposal and applies it. So this server answers with exactly the tool calls
those steps need.

    python e2e/stand_in_claude.py 8799

Then run the app with ANTHROPIC_BASE_URL=http://localhost:8799 and the smoke
test with CLAUDE_STAND_IN=1.
"""

from __future__ import annotations

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


def _message(text: str = "", calls=None) -> dict:
    """One Messages API response, in the shape the SDK parses."""
    content: list[dict] = []
    if text:
        content.append({"type": "text", "text": text})
    for name, arguments in calls or []:
        content.append({"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:16]}",
                        "name": name, "input": arguments})
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": "tool_use" if calls else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _last_text(entry) -> str:
    """The words in a message, whatever shape its content came in."""
    content = entry.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(block.get("text") or "") for block in content
                        if isinstance(block, dict) and block.get("type") == "text")
    return ""


def answer(messages: list) -> dict:
    """What the stand-in says next, from what it has been sent so far."""
    # Already given tool results? Then say something in words.
    last = messages[-1] if messages else {}
    blocks = last.get("content") if isinstance(last.get("content"), list) else []
    results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
    if results:
        said = " ".join(str(b.get("content") or "") for b in results)
        if "staged" in said:
            return _message("I have staged that change. Press Apply and it is recorded.")
        return _message("Earned progress is behind planned, and the float against the "
                        "contract date is tight.")

    asked = ""
    for entry in reversed(messages):
        if entry.get("role") == "user":
            asked = _last_text(entry).lower()
            break

    if "40" in asked and "1.1" in asked:
        return _message("", [("set_progress", {"reference": "1.1", "percent": 40,
                                               "note": "asked for in the chat"})])
    # A file to hand back rather than an answer.
    if "document" in asked or "as a file" in asked:
        return _message("", [("document", {"what": "register", "form": "word",
                                           "register": "client"})])
    if "minute" in asked:
        return _message("", [("minute_meeting", {
            "register": "client", "ref": "MOM-09", "title": "Coordination call",
            "date": "10/09/2026", "time": "11:00", "location": "Teams",
            "attendees": [{"name": "Jihad Zuhairy", "organisation": "Sibline",
                           "role": "Port Manager"}],
            "items": [{"subject": "Bathymetry survey",
                       "discussion": "The client asked when it starts.",
                       "agreement": "Dar to issue the brief.", "owner": "PM",
                       "impact": "time", "due": "20/09/2026"}]})])
    # The bulk change, in the two steps it actually takes: the trade has to
    # exist before it can be given a share of anything.
    if "project manager" in asked and "%" in asked:
        return _message("", [("share_across", {"trade": "Project Manager", "percent": 10})])
    if "project manager" in asked:
        return _message("", [("set_trade", {"trade": "Project Manager", "office": "Beirut",
                                            "budget_hours": 400})])
    if "office" in asked and ("cairo" in asked or "beirut" in asked):
        return _message("", [("set_trade", {"trade": "Utilities", "office": "Cairo"})])
    if "take me" in asked or "go to" in asked:
        return _message("", [("open_view", {"view": "schedule"})])
    if "presentation" in asked or "deck" in asked:
        return _message("", [("presentation", {"start": "01/08/2026", "end": "06/09/2026"})])
    if "print" in asked:
        return _message("", [("open_view", {"view": "schedule", "printable": True})])
    return _message("", [("overview", {})])


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):                                # noqa: N802 - the name http.server wants
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send(answer(body.get("messages") or []))

    def do_GET(self):                                 # noqa: N802
        # GET /v1/models
        self._send({"data": [{"id": "claude-opus-5", "type": "model",
                              "display_name": "Claude Opus 5"},
                             {"id": "stand-in", "type": "model",
                              "display_name": "Stand-in"}],
                    "has_more": False, "first_id": None, "last_id": None})

    def _send(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("request-id", "req_stand_in")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):                    # keep the terminal clean
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"Stand-in Anthropic API on http://localhost:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
