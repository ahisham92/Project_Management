"""The assistant: the page, the question, and doing what it proposed."""

from __future__ import annotations

import io
import json

from flask import (
    Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
    send_file, url_for,
)

from ..auth import ROLE_RANK, load_project, login_required, setup_unlocked
from ..dates import from_input, to_display
from ..service import note_applied, record_chat, today

bp = Blueprint("assistant", __name__, url_prefix="/projects/<int:project_id>")


@bp.app_context_processor
def _carmen_context():
    """What the pop-up in the corner of every page needs to draw itself."""
    from ..vault import carmen

    project_id = (request.view_args or {}).get("project_id")
    if not project_id or not g.get("user"):
        return {}
    try:
        role = g.get("project_role") or "viewer"
        return {"carmen_ready": bool(carmen()["key"]), "carmen_can_write": _can_write(role)}
    except Exception:                                 # noqa: BLE001 - never break a page
        return {"carmen_ready": False, "carmen_can_write": False}

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
    """The chat, its conversations, and — for an administrator — the key.

    A conversation is picked with ``?thread=``. Somebody's own threads are what
    they see; a manager can ask for everybody's, because "what is this being
    used for" is a question they are meant to be able to answer.
    """
    from ..claude import DEFAULT_MODEL, EFFORTS
    from ..service import load_thread, load_threads, thread_messages
    from ..vault import carmen

    project, role = load_project(project_id)
    held = carmen()

    everyone = (request.args.get("who") == "all"
                and ROLE_RANK[role] >= ROLE_RANK["manager"])
    threads = load_threads(project_id, None if everyone else g.user["id"])

    wanted = request.args.get("thread")
    thread = load_thread(project_id, wanted) if wanted else None
    messages = thread_messages(thread["id"]) if thread else []

    return render_template(
        "assistant.html",
        project=project, role=role, today=today(),
        ready=bool(held["key"]), model=held["model"], from_env=held["from_env"],
        effort=held["effort"], efforts=EFFORTS, default_model=DEFAULT_MODEL,
        is_admin=g.user["role"] == "admin",
        can_write=_can_write(role),
        can_see_everyone=ROLE_RANK[role] >= ROLE_RANK["manager"],
        everyone=everyone, threads=threads, thread=thread, messages=messages,
        suggestions=SUGGESTIONS,
    )


@bp.post("/assistant/threads/<int:thread_id>/rename")
@login_required
def rename_conversation(project_id: int, thread_id: int):
    from ..service import rename_thread

    load_project(project_id)
    if not rename_thread(project_id, thread_id, request.form.get("title") or ""):
        flash("That conversation could not be renamed", "error")
    return redirect(url_for("assistant.index", project_id=project_id, thread=thread_id))


@bp.post("/assistant/threads/<int:thread_id>/delete")
@login_required
def delete_conversation(project_id: int, thread_id: int):
    from ..service import delete_thread, load_thread

    _project, role = load_project(project_id)
    found = load_thread(project_id, thread_id)
    if found is None:
        abort(404)
    # Your own, or anybody's if you run the project.
    if found["user_id"] != g.user["id"] and ROLE_RANK[role] < ROLE_RANK["manager"]:
        flash("That conversation is somebody else's", "error")
        return redirect(url_for("assistant.index", project_id=project_id))

    delete_thread(project_id, thread_id)
    flash("Conversation removed from the list — what was said stays in the log", "success")
    return redirect(url_for("assistant.index", project_id=project_id))


SUGGESTIONS = (
    "How is the project doing?",
    "What is late, and by how much?",
    "What does this week need?",
    "Give the Project Manager 10% of every deliverable",
    "Prepare a presentation of the work done in the last month",
    "Set 1.1 to 40% — the drawings went out today",
    "Move 2.1 to start on 15/10/2026",
    "Squeeze 1.1 to 1.6 into 40 working days",
    "How are Beirut and Cairo doing against their scope?",
    "Put Utilities under Cairo and set its budget to 120 hours",
    "Print the schedule as a PDF",
    "What is on the critical path?",
)


@bp.post("/assistant/ask")
@login_required
def ask(project_id: int):
    """One question. Reading happens; changing is staged for approval."""
    from ..assistant import ask as ask_it
    from ..vault import carmen

    project, role = load_project(project_id)
    held = carmen()
    if not held["key"]:
        return jsonify({"ok": False, "error":
                        "Carmen is not connected yet — an administrator adds an "
                        "Anthropic API key on her tab."}), 400

    from ..service import load_thread, open_thread, thread_messages

    asked = _asked()
    question = str(asked.get("question") or "")[:MAX_QUESTION]

    # A question belongs to a conversation. Given one, it carries on; given
    # none, it starts one — so nothing has to be pressed before asking.
    thread_id = asked.get("thread_id")
    thread = load_thread(project_id, thread_id) if thread_id else None
    if thread is None:
        thread_id = open_thread(project_id, g.user, question)
    else:
        thread_id = thread["id"]

    # The thread on the server is the history, so a page reopened a week later
    # picks up exactly where the conversation was.
    history = [{"role": m["role"], "content": m["content"]}
               for m in thread_messages(thread_id) if m["content"]]

    try:
        answer = ask_it(project, question, held["key"], held["model"],
                        history[-MAX_HISTORY:], today(), held["effort"])
    except Exception as exc:                          # noqa: BLE001 - said, not swallowed
        # Never an HTML 500 here. The page can only show what it is given, and
        # "Carmen could not be reached" while the real reason sits in a server
        # log sends somebody to check a key, a network and a host that were all
        # fine.
        current_app.logger.exception("Carmen failed on a question")
        return jsonify({"ok": False,
                        "error": f"{type(exc).__name__}: {exc}"}), 500

    # Somebody who may not write to the project may still ask about it; what
    # they cannot do is apply anything, so they are not offered the button.
    if not _can_write(role):
        answer.staged = []

    said = answer.as_json()
    # Written down whether it worked or not: a week of failures is the thing
    # worth noticing, and it is invisible if only the answers are kept.
    said["chat_id"] = record_chat(project_id, g.user, question, answer, thread_id)
    said["thread_id"] = thread_id
    return jsonify(said), (200 if not answer.trouble else 502)


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
    # Changing the setup sheet takes what changing it takes on the Setup tab:
    # manager access, and the sheet unlocked in this person's own session.
    is_manager = ROLE_RANK[role] >= ROLE_RANK["manager"]
    setup_open = is_manager and setup_unlocked(project_id)

    asked = _asked()
    actions = asked.get("actions") or []
    if isinstance(actions, str):
        actions = json.loads(actions or "[]")
    if not isinstance(actions, list) or not actions:
        return jsonify({"ok": False, "error": "There is nothing to apply"}), 400
    if len(actions) > 20:
        return jsonify({"ok": False, "error": "That is too many changes at once"}), 400

    try:
        done = apply_them(project_id, actions, g.user["id"], today(), setup_open, is_manager)
    except ApplyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:                          # noqa: BLE001 - said, not swallowed
        current_app.logger.exception("Applying an assistant change failed")
        return jsonify({"ok": False, "error": f"That change was refused: {exc}"}), 400

    note_applied(asked.get("chat_id"), len(done))
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


@bp.get("/assistant/face")
@login_required
def face(project_id: int):
    """Carmen's picture — the uploaded one, or the drawn monogram."""
    from flask import Response, send_file

    from . import carmen_avatar as avatar

    load_project(project_id)
    where = avatar.saved()
    if where is None:
        return Response(avatar.MONOGRAM, mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=300"})
    return send_file(where, mimetype=avatar.content_type(where),
                     max_age=300, last_modified=where.stat().st_mtime)


@bp.post("/assistant/face")
@login_required
def set_face(project_id: int):
    """Upload a picture for her, or take the one there away."""
    from . import carmen_avatar as avatar

    load_project(project_id)
    # The picture is set on Setup with the key; the endpoint answers to either
    # page so a form can live wherever it reads best.
    where = ("projects.setup" if (request.form.get("back") or "") == "setup"
             else "assistant.index")

    if g.user["role"] != "admin":
        flash("Only an administrator can change Carmen's picture", "error")
        return redirect(url_for(where, project_id=project_id))

    if request.form.get("remove"):
        avatar.forget()
        flash("Carmen is back to the picture she came with", "success")
        return redirect(url_for(where, project_id=project_id))

    upload = request.files.get("picture")
    data = upload.read(avatar.MAX_BYTES + 1) if upload else b""
    if not data:
        flash("Choose a picture first", "error")
        return redirect(url_for(where, project_id=project_id))

    try:
        avatar.store(data)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for(where, project_id=project_id))

    flash("That is Carmen now — everybody sees it", "success")
    return redirect(url_for(where, project_id=project_id))


@bp.get("/assistant/test")
@login_required
def test_connection(project_id: int):
    """Why nothing works, when nothing works.

    A 403 from a host's own outbound proxy and a 403 from Anthropic read identically
    in a log and need completely different fixes, so this asks the three
    questions in order and says which one failed.
    """
    from ..claude import diagnose
    from ..vault import carmen

    load_project(project_id)
    if g.user["role"] != "admin":
        return jsonify({"ok": False, "error": "Administrators only"}), 403

    found = diagnose(carmen()["key"])
    return jsonify({"ok": bool(found["key_works"]), **found})


@bp.get("/assistant/ping")
@login_required
def ping(project_id: int):
    """One real question, end to end, with no tools in the way.

    "Connected" on the badge only ever meant a key is saved. This is the thing
    that actually proves she works: the smallest possible request to the model
    the settings name, and whatever comes back.
    """
    from ..claude import ClaudeError, chat, said
    from ..vault import carmen

    load_project(project_id)
    if g.user["role"] != "admin":
        return jsonify({"ok": False, "error": "Administrators only"}), 403

    held = carmen()
    if not held["key"]:
        return jsonify({"ok": False, "error": "There is no API key saved yet"}), 400

    try:
        answer = chat(held["key"], "Reply with the single word: ready.",
                      [{"role": "user", "content": "Are you there?"}],
                      None, held["model"], "low")
    except ClaudeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "detail": f"{held['model']} answered: {said(answer)[:120]}"})


@bp.post("/assistant/settings")
@login_required
def settings(project_id: int):
    """The key and the model. Administrators only — it is an account-wide key."""
    from ..vault import update

    load_project(project_id)
    # Whichever page the form was on — the key lives on Setup, and somebody who
    # saved it there should still be looking at Setup afterwards.
    where = ("projects.setup" if (request.form.get("back") or "") == "setup"
             else "assistant.index")
    if g.user["role"] != "admin":
        flash("Only an administrator can connect Carmen", "error")
        return redirect(url_for(where, project_id=project_id))

    from ..claude import EFFORTS

    key = (request.form.get("anthropic_key") or "").strip()
    model = (request.form.get("anthropic_model") or "").strip()
    effort = (request.form.get("anthropic_effort") or "").strip()

    if request.form.get("disconnect"):
        update(anthropic_key="", anthropic_model="", anthropic_effort="")
        flash("Carmen is disconnected — the key is gone", "success")
        return redirect(url_for(where, project_id=project_id))

    changes: dict[str, str] = {"anthropic_model": model,
                               "anthropic_effort": effort if effort in EFFORTS else ""}
    if key:
        changes["anthropic_key"] = key
    update(**changes)
    flash("Saved. Ask her something to check it works.", "success")
    return redirect(url_for(where, project_id=project_id))


@bp.get("/assistant/models")
@login_required
def models(project_id: int):
    """Which models this account can actually use, read from Anthropic itself."""
    from ..claude import ClaudeError, models as list_them
    from ..vault import carmen

    load_project(project_id)
    if g.user["role"] != "admin":
        return jsonify({"ok": False, "error": "Administrators only"}), 403

    held = carmen()
    if not held["key"]:
        return jsonify({"ok": False, "error": "Add a key first"}), 400
    try:
        return jsonify({"ok": True, "models": list_them(held["key"]), "using": held["model"]})
    except ClaudeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
