"""Questions handed to a team (the materials team, the marine unit) before the
IDC: asked from a question's card, answered by the team with the question's
own buttons, accepted into the specification by its engineers. The routes
join the THEMIS blueprint."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import abort, flash, g, redirect, render_template, request, url_for

from .. import specs, specs_asks, specs_places, specs_questions
from .. import specs_review as review
from .. import specs_store as store
from ..auth import login_required
from .specs_review_views import SELF_CHECKED
from .specs_views import _asked, _labels, _set_or_404, bp

# The team answers on a specification it may not change: the route checks
# for itself that the one answering is in the team asked.
SELF_CHECKED.update({"specs.ask_answer"})


@bp.app_template_global("themis_teams")
def themis_teams() -> list[dict]:
    return specs_asks.choices()


@bp.app_template_global("themis_team_name")
def themis_team_name(code: str) -> str:
    return specs_asks.name(code)


@bp.app_template_global("shown_answer")
def shown_answer(a) -> str:
    """A team's answer in words."""
    return specs_asks.shown(a["given"], a["qkey"])


@bp.app_template_global("themis_asks_live")
def themis_asks_live(spec) -> dict:
    """The questions of a specification that are with a team, by key."""
    cache = g.setdefault("themis_asks_live", {})
    if spec["id"] not in cache:
        try:
            cache[spec["id"]] = specs_asks.live_by_key(spec["id"])
        except Exception:                  # a page of a project being deleted
            cache[spec["id"]] = {}
    return cache[spec["id"]]


@bp.app_template_global("themis_team_inbox")
def themis_team_inbox() -> list[dict]:
    """The questions waiting on the signed-in engineer's team."""
    return specs_asks.for_team(specs_asks.of_user(g.get("user")))


@bp.app_template_global("themis_answers_to_accept")
def themis_answers_to_accept(spec=None) -> list[dict]:
    """The teams' answers waiting on the signed-in engineer to accept, on one
    specification or on all they may change."""
    if g.get("user") is None:
        return []
    found = specs_asks.answered_for(g.user)
    return [a for a in found if spec is None or a["set_id"] == spec["id"]]


def _question(set_id: int, row: dict, key: str) -> dict | None:
    return next((q for q in _asked(set_id, row) if q["key"] == key), None)


def _back(default: str) -> str:
    """Where the page was opened from, when that is a THEMIS page."""
    for given in (request.values.get("back"), request.referrer):
        if given:
            path = urlparse(given)
            if path.path.startswith("/specs/") and "/ask" not in path.path and (
                    not path.netloc or path.netloc == request.host):
                return (path.path + (f"?{path.query}" if path.query else "")
                        + (f"#{path.fragment}" if path.fragment else ""))
    return default


@bp.get("/sets/<int:set_id>/ask/<key>")
@login_required
def ask_page(set_id: int, key: str):
    """One question and its asks: to ask a team for it, to answer it for the
    team, or to accept the team's answer."""
    row = _set_or_404(set_id)
    q = _question(set_id, row, key)
    asks = [a for a in specs_asks.of_set(set_id) if a["qkey"] == key]
    if q is None and not asks:
        abort(404)
    live = next((a for a in asks if a["state"] in (specs_asks.ASKED, specs_asks.ANSWERED)), None)
    shown_q = dict(q) if q else None
    if shown_q and live and live["given"]:
        # The team's answer shown on the buttons, for the team to change and
        # for the engineer to see as it would be written in.
        shown_q.update(answer=live["given"].get(key), answered=key in live["given"],
                       split=bool(live["split"].get(key)),
                       row_answers={e: live["given"].get(f"{key}@{e}") for e in shown_q.get("rows") or []})
    return render_template(
        "specs/ask.html", spec=row, q=shown_q, key=key, label=(q or asks[0])["label"] if q else asks[0]["label"],
        asks=asks, live=live, back=_back(url_for("specs.story", set_id=set_id)),
        may_ask=review.may(row, g.user, "edit") and live is None and q is not None,
        may_answer=bool(live) and specs_asks.may_answer(live, g.user),
        may_decide=bool(live) and specs_asks.may_decide(row, live, g.user),
        may_withdraw=bool(live) and review.may(row, g.user, "edit"),
        teams=[dict(t, people=specs_asks.members(t["code"])) for t in specs_asks.choices()],
        no_ask=True, element_labels=_labels(), split_location=specs_places.split_location,
        FREE=specs_questions.FREE, NONE=specs_questions.NONE, SAME=specs_questions.SAME,
        picked=specs_questions.picked, shown=specs_questions.shown, KEEP=specs.KEEP)


@bp.post("/sets/<int:set_id>/ask/<key>")
@login_required
def ask_send(set_id: int, key: str):
    row = _set_or_404(set_id)
    back = request.form.get("back") or url_for("specs.story", set_id=set_id)
    q = _question(set_id, row, key)
    if q is None:
        abort(404)
    to_user = request.form.get("to_user", "")
    try:
        specs_asks.send(row, q, request.form.get("team", ""), request.form.get("note", ""), g.user,
                        int(to_user) if to_user.isdigit() else None)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.ask_page", set_id=set_id, key=key, back=back))
    team = specs_asks.name(request.form.get("team"))
    flash(f"Asked the {team}. They see it on their THEMIS start page; their answer comes back here for "
          "you to accept before anything is written in. Carry on with the other questions meanwhile.", "success")
    return redirect(_safe(back, url_for("specs.story", set_id=set_id)))


def _safe(target: str, default: str) -> str:
    return target if target.startswith("/specs/") else default


def _ask_of(set_id: int, ask_id: int) -> dict:
    a = specs_asks.ask(ask_id)
    if a is None or a["set_id"] != set_id:
        abort(404)
    return a


@bp.post("/sets/<int:set_id>/asks/<int:ask_id>/answer")
@login_required
def ask_answer(set_id: int, ask_id: int):
    row = _set_or_404(set_id)
    a = _ask_of(set_id, ask_id)
    page = url_for("specs.ask_page", set_id=set_id, key=a["qkey"])
    if not specs_asks.may_answer(a, g.user):
        flash(f"Only the {a['team_name']} answers this, while it waits on them.", "error")
        return redirect(page)
    q = _question(set_id, row, a["qkey"])
    if q is None:
        flash("The project no longer asks this question.", "error")
        return redirect(page)
    given, split = specs_questions.read_form(request.form, [q])
    try:
        specs_asks.answer(a, given, split, request.form.get("why", ""), g.user)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(page)
    flash(f"Answer sent to {a['asked_by_name']} to accept.", "success")
    return redirect(url_for("specs.index"))


@bp.post("/sets/<int:set_id>/asks/<int:ask_id>/decide")
@login_required
def ask_decide(set_id: int, ask_id: int):
    row = _set_or_404(set_id)
    a = _ask_of(set_id, ask_id)
    page = url_for("specs.ask_page", set_id=set_id, key=a["qkey"])
    how = request.form.get("how")
    back = _safe(request.form.get("back") or "", page)
    if how == "withdraw" and a["state"] in (specs_asks.ASKED, specs_asks.ANSWERED):
        specs_asks.withdraw(a, g.user)
        flash(f"Taken back from the {a['team_name']}: answer it yourself.", "success")
        return redirect(back)
    if not specs_asks.may_decide(row, a, g.user):
        flash("Only this specification's engineers accept a team's answer, and not the one who gave it.", "error")
        return redirect(page)
    if how == "accept":
        specs_asks.accept(a, g.user)
        flash(f"The {a['team_name']}'s answer is written in: {specs_asks.shown(a['given'], a['qkey'])}.", "success")
        return redirect(back)
    if how == "back":
        try:
            specs_asks.send_back(a, request.form.get("why", ""), g.user)
        except specs.SpecError as exc:
            flash(str(exc), "error")
            return redirect(page)
        flash(f"Sent back to the {a['team_name']} with your note.", "success")
        return redirect(back)
    abort(400)


@bp.get("/sets/<int:set_id>/asks")
@login_required
def asks_page(set_id: int):
    """Every question of a specification handed to a team, and where each stands."""
    row = _set_or_404(set_id)
    return render_template("specs/asks.html", spec=row, asks=specs_asks.of_set(set_id),
                           STATE_NAMES=specs_asks.STATE_NAMES)
