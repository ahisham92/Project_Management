"""A stand-in for Groq, so the browser test can exercise the assistant.

Pointing a smoke test at a real paid API would make it slow, flaky and
expensive, and would test somebody else's uptime rather than this app. What is
worth checking is everything on this side of the wire: that a tool call is run
and fed back, that a change is staged rather than done, and that the page draws
the proposal and applies it. So this server answers with exactly the tool calls
those steps need.

    python e2e/stand_in_groq.py 8799

Then run the app with GROQ_BASE_URL=http://localhost:8799/openai/v1 and the
smoke test with GROQ_STAND_IN=1.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def _reply(content: str = "", calls=None) -> dict:
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": f"c{number}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(arguments)}}
            for number, (name, arguments) in enumerate(calls, start=1)
        ]
    return {"choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def answer(messages: list) -> dict:
    """What the stand-in says next, from what it has been sent so far."""
    # Already given tool results? Then say something in words.
    if messages and messages[-1].get("role") == "tool":
        said = str(messages[-1].get("content") or "")
        if "staged" in said:
            return _reply("I have staged that change. Press Apply and it is recorded.")
        return _reply("Earned progress is behind planned, and the float against the "
                      "contract date is tight.")

    asked = ""
    for turn in reversed(messages):
        if turn.get("role") == "user":
            asked = str(turn.get("content") or "").lower()
            break

    if "40" in asked and "1.1" in asked:
        return _reply("", [("set_progress", {"reference": "1.1", "percent": 40,
                                             "note": "asked for in the chat"})])
    if "minute" in asked:
        return _reply("", [("minute_meeting", {
            "register": "client", "ref": "MOM-09", "title": "Coordination call",
            "date": "10/09/2026", "time": "11:00", "location": "Teams",
            "attendees": [{"name": "Jihad Zuhairy", "organisation": "Sibline",
                           "role": "Port Manager"}],
            "items": [{"subject": "Bathymetry survey",
                       "discussion": "The client asked when it starts.",
                       "agreement": "Dar to issue the brief.", "owner": "PM",
                       "impact": "time", "due": "20/09/2026"}]})])
    if "take me" in asked or "go to" in asked:
        return _reply("", [("open_view", {"view": "schedule"})])
    if "presentation" in asked or "deck" in asked:
        return _reply("", [("presentation", {"start": "01/08/2026", "end": "06/09/2026"})])
    if "print" in asked:
        return _reply("", [("open_view", {"view": "schedule", "printable": True})])
    return _reply("", [("overview", {})])


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):                                # noqa: N802 - the name http.server wants
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send(answer(body.get("messages") or []))

    def do_GET(self):                                 # noqa: N802
        self._send({"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "stand-in"}]})

    def _send(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):                    # keep the terminal clean
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"Stand-in Groq on http://localhost:{port}/openai/v1")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
