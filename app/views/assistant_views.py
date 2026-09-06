"""The assistant: the page, the question, and doing what it proposed."""

from __future__ import annotations

import io
import json

from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template, request,
    send_file, url_for,
)

from ..auth import ROLE_RANK, load_project, login_required
from ..dates import from_input, to_display
from ..service import today

bp = Blueprint("assistant", __name__, url_prefix="/projects/<int:project_id>")

# What one question may carry back. A page that has been open all afternoon
# should not be able to post a megabyte of "history".
MAX_QUESTION = 2000
MAX_HISTORY = 24


def _can_write(role: str) -> bool:
    """Applying what the assistant proposed is writing to the project, so it
    takes exactly what writing to the project takes anywhere else."""
    return ROLE_RANK[role] >= ROLE_RANK["member"]


def _asked() -> dict:
    if request.is_json:
        return dict(request.get_json(silent=True) or {})
    return dict(request.form)


@bp.get("/assistant")
@login_required
def index(project_id: int):
    """The chat, and — for an administrator — where the key goes."""
    from ..groq import DEFAULT_MODEL
    from ..vault import groq

    project, role = load_project(project_id)
    held = groq()
    return render_template(
        "assistant.html",
        project=project, role=role, today=today(),
        ready=bool(held["key"]), model=held["model"], from_env=held["from_env"],
        default_model=DEFAULT_MODEL,
        is_admin=g.user["role"] == "admin",
        can_write=_can_write(role),
        suggestions=SUGGESTIONS,
    )


SUGGESTIONS = (
    "How is the project doing?",
    "What is late, and by how much?",
    "What does this week need?",
    "Prepare a presentation of the work done in the last month",
    "Set 1.1 to 40% — the drawings went out today",
    "Move 2.1 to start on 15/10/2026",
    "Print the schedule as a PDF",
    "What is on the critical path?",
)


@bp.post("/assistant/ask")
@login_required
def ask(project_id: int):
    """One question. Reading happens; changing is staged for approval."""
    from ..assistant import ask as ask_it
    from ..vault import groq

    project, role = load_project(project_id)
    held = groq()
    if not held["key"]:
        return jsonify({"ok": False, "error":
                        "The assistant is not connected yet — an administrator adds a "
                        "Groq API key on this page."}), 400

    asked = _asked()
    question = str(asked.get("question") or "")[:MAX_QUESTION]
    history = asked.get("history") or []
    if not isinstance(history, list):
        history = []

    answer = ask_it(project, question, held["key"], held["model"],
                    history[-MAX_HISTORY:], today())

    # Somebody who may not write to the project may still ask about it; what
    # they cannot do is apply anything, so they are not offered the button.
    if not _can_write(role):
        answer.staged = []
    return jsonify(answer.as_json()), (200 if not answer.trouble else 502)


@bp.post("/assistant/apply")
@login_required
def apply(project_id: int):
    """Carries out the changes the reader approved.

    Every one goes through the same service function a form posts to, and this
    view takes the same role a form does — the assistant is another way in, not
    another set of rules. That is also why it is safe for the staged list to
    come back from the page: nothing here can be asked for that could not be
    asked for on the screens.
    """
    from ..assistant.runner import ApplyError, apply as apply_them, staged_summary

    _project, role = load_project(project_id, "member")

    asked = _asked()
    actions = asked.get("actions") or []
    if isinstance(actions, str):
        actions = json.loads(actions or "[]")
    if not isinstance(actions, list) or not actions:
        return jsonify({"ok": False, "error": "There is nothing to apply"}), 400
    if len(actions) > 20:
        return jsonify({"ok": False, "error": "That is too many changes at once"}), 400

    try:
        done = apply_them(project_id, actions, g.user["id"], today())
    except ApplyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:                          # noqa: BLE001 - said, not swallowed
        current_app.logger.exception("Applying an assistant change failed")
        return jsonify({"ok": False, "error": f"That change was refused: {exc}"}), 400

    return jsonify({"ok": True, "done": done, "note": staged_summary(actions)})


@bp.get("/assistant/deck.pptx")
@login_required
def deck(project_id: int):
    """A slide deck of the work done between two dates."""
    from ..assistant.deck_of import build

    project, _role = load_project(project_id)
    start = from_input(request.args.get("start"))
    end = from_input(request.args.get("end"))
    if not start or not end:
        flash("A presentation needs a start and an end date", "error")
        return redirect(url_for("assistant.index", project_id=project_id))
    if end < start:
        start, end = end, start

    data = build(project, start, end, (request.args.get("title") or "").strip()[:120])
    stem = f"{project['code']}-progress-{start.replace('-', '')}-{end.replace('-', '')}"
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        as_attachment=True, download_name=f"{stem}.pptx",
    )


@bp.post("/assistant/settings")
@login_required
def settings(project_id: int):
    """The key and the model. Administrators only — it is an account-wide key."""
    from ..vault import update

    load_project(project_id)
    if g.user["role"] != "admin":
        flash("Only an administrator can connect the assistant", "error")
        return redirect(url_for("assistant.index", project_id=project_id))

    key = (request.form.get("groq_key") or "").strip()
    model = (request.form.get("groq_model") or "").strip()

    if request.form.get("disconnect"):
        update(groq_key="", groq_model="")
        flash("The assistant is disconnected — the key is gone", "success")
        return redirect(url_for("assistant.index", project_id=project_id))

    changes: dict[str, str] = {"groq_model": model}
    if key:
        changes["groq_key"] = key
    update(**changes)
    flash("Saved. Ask it something to check it works.", "success")
    return redirect(url_for("assistant.index", project_id=project_id))


@bp.get("/assistant/models")
@login_required
def models(project_id: int):
    """Which models this account can actually use, read from Groq itself."""
    from ..groq import GroqError, models as list_them
    from ..vault import groq

    load_project(project_id)
    if g.user["role"] != "admin":
        return jsonify({"ok": False, "error": "Administrators only"}), 403

    held = groq()
    if not held["key"]:
        return jsonify({"ok": False, "error": "Add a key first"}), 400
    try:
        return jsonify({"ok": True, "models": list_them(held["key"]), "using": held["model"]})
    except GroqError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
