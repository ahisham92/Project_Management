"""Review, approval and issue control, as pages: the team and sign-off, the
issue register, what changed since an issue, reviewers' comments, and the
history of every change. The routes join the THEMIS blueprint."""

from __future__ import annotations

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from markupsafe import Markup

from .. import specs
from .. import specs_review as review
from .. import specs_store as store
from ..auth import login_required
from .specs_views import _bundle, _not_issued, _set_or_404, bp

# Routes that decide for themselves who may use them; every other form sent to a
# project is refused to anyone its team does not let change it.
SELF_CHECKED = {"specs.save_team", "specs.sign_sections", "specs.withdraw_signoff",
                "specs.issue_set", "specs.add_comment", "specs.close_comment",
                "specs.reopen_comment", "specs.delete_set"}


@bp.before_request
def _guard_and_watch():
    """A form sent to a project: refused to anyone not on its team (when it
    has one), and what the project looked like kept, so that every answer and
    paragraph the form changes goes into its history."""
    if request.method != "POST" or g.get("user") is None:
        return None
    set_id = (request.view_args or {}).get("set_id")
    if not set_id:
        return None
    row = store.spec_set(set_id)
    if row is None:
        return None
    if request.endpoint not in SELF_CHECKED and not review.may(row, g.user, "edit"):
        flash("Only this project's team changes it. Ask its lead to add you on the Review page.",
              "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    g.spec_before = review.state(set_id)
    return None


@bp.after_request
def _write_history(response):
    before = g.pop("spec_before", None)
    if before is not None:
        review.record(before, review.state(before["set_id"]))
    return response


@bp.app_template_filter("ago")
def _ago(stamp: str) -> str:
    return review.minutes_ago(stamp or "")


# --- the team and sign-off ------------------------------------------------------------

@bp.get("/sets/<int:set_id>/review")
@login_required
def review_set(set_id: int):
    row = _set_or_404(set_id)
    report = store.check_set(set_id) if store.set_sections(set_id) else None
    ready = review.readiness(row, report)
    members = {m["user_id"]: m["role"] for m in review.team(set_id)}
    people = review.candidates()
    return render_template(
        "specs/review.html", spec=row, ready=ready, team=review.team(set_id), members=members,
        people=people, is_open=review.is_open(set_id), my_role=review.role_of(row, g.user),
        may={w: review.may(row, g.user, w) for w in ("edit", "prepared", "checked", "approved",
                                                     "issue", "team")},
        open_by_section=review.open_by_section(set_id), last=review.last_issue(set_id),
        take_back=_take_back(row),
        STAGES=review.STAGES, STAGE_NAMES=review.STAGE_NAMES, ROLES=review.ROLES,
        ROLE_NAMES=review.ROLE_NAMES, ROLE_HINTS=review.ROLE_HINTS)


def _take_back(row: dict):
    lead = review.role_of(row, g.user) == "lead"
    return lambda s: lead or (g.user is not None and s["user_id"] == g.user["id"])


@bp.post("/sets/<int:set_id>/team")
@login_required
def save_team(set_id: int):
    row = _set_or_404(set_id)
    if not review.may(row, g.user, "team"):
        flash("Only the project's lead or an administrator chooses its team.", "error")
        return redirect(url_for("specs.review_set", set_id=set_id) + "#team")
    roles = {}
    for key, value in request.form.items():
        if key.startswith("role_") and key[5:].isdigit():
            roles[int(key[5:])] = value
    roles.pop(row["created_by"], None)          # whoever started it leads it anyway
    said = review.save_team(set_id, roles)
    flash(("Team saved: " + "; ".join(said) + ".") if said else "Nothing changed in the team.",
          "success")
    if said and review.is_open(set_id):
        flash("Nobody is listed, so everyone with THEMIS can change and issue this project again.",
              "notice")
    return redirect(url_for("specs.review_set", set_id=set_id) + "#team")


@bp.post("/sets/<int:set_id>/signoff")
@login_required
def sign_sections(set_id: int):
    row = _set_or_404(set_id)
    stage = request.form.get("stage", "")
    picked = [int(v) for v in request.form.getlist("row_id") if v.isdigit()]
    back = request.form.get("back") or url_for("specs.review_set", set_id=set_id)
    if not picked:
        flash("Tick the sections to sign first.", "error")
        return redirect(_safe(back, set_id))
    try:
        done, refused = review.sign(row, picked, stage)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(_safe(back, set_id))
    if done:
        flash(f"Signed as {stage}: {', '.join(done)}.", "success")
    if refused:
        flash("Not signed: " + "; ".join(refused) + ".", "error")
    return redirect(_safe(back, set_id))


@bp.post("/sets/<int:set_id>/signoff/withdraw")
@login_required
def withdraw_signoff(set_id: int):
    row = _set_or_404(set_id)
    row_id = request.form.get("row_id", type=int)
    stage = request.form.get("stage", "")
    back = request.form.get("back") or url_for("specs.review_set", set_id=set_id)
    if stage not in review.STAGES or not row_id:
        abort(400)
    try:
        if review.unsign(row, row_id, stage):
            flash(f"Took back the {stage} sign-off"
                  + (" and the ones after it." if stage != "approved" else "."), "success")
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return redirect(_safe(back, set_id))


def _safe(back: str, set_id: int) -> str:
    """Back to a page of this site only."""
    return back if back.startswith("/specs/") and not back.startswith("//") else \
        url_for("specs.review_set", set_id=set_id)


# --- the issue register ------------------------------------------------------------------

@bp.get("/sets/<int:set_id>/issues")
@login_required
def issues(set_id: int):
    row = _set_or_404(set_id)
    sections = store.set_sections(set_id)
    report = store.check_set(set_id) if sections else None
    ready = review.readiness(row, report) if sections else None
    listed = review.issues(set_id)
    last = listed[0] if listed else None
    return render_template(
        "specs/issues.html", spec=row, issues=listed, ready=ready, sections=sections,
        missing=_not_issued(report) if report else [], last=last,
        suggested=review.next_revision(row["revision"], [i["revision"] for i in listed]),
        today=review.clean_date(""), purposes=review.PURPOSES,
        may_issue=review.may(row, g.user, "issue"))


@bp.post("/sets/<int:set_id>/issues")
@login_required
def issue_set(set_id: int):
    row = _set_or_404(set_id)
    back = url_for("specs.issues", set_id=set_id)
    if not review.may(row, g.user, "issue"):
        flash("Your role on this project does not issue it: an approver or the lead does.", "error")
        return redirect(back)
    sections = store.set_sections(set_id)
    if not sections:
        flash("There are no sections in this specification to issue yet.", "error")
        return redirect(back)
    report = store.check_set(set_id)
    ready = review.readiness(row, report)
    if ready["reasons"]:
        flash("Not issued yet: " + "; ".join(ready["reasons"]) + ".", "error")
        return redirect(back)
    if _not_issued(report) and not row["hold_issue"] and not request.form.get("anyway"):
        flash("Not issued yet: some references point at sections or paragraphs this issue does not "
              "contain. Correct them on the check, or tick Issue anyway.", "error")
        return redirect(back)
    try:
        revision = review.check_revision(set_id, request.form.get("revision", ""))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(back)
    purpose = request.form.get("purpose", "")
    if purpose == "__other__":
        purpose = " ".join(request.form.get("purpose_other", "").split())
    fields = {"revision": revision, "purpose": purpose[:120],
              "issue_date": review.clean_date(request.form.get("issue_date", "")),
              "note": (request.form.get("note") or "").strip()[:2000]}
    fmt = request.form.get("fmt", "docx")
    since = review.last_issue(set_id) if fmt == "since" else None
    if fmt == "since" and since is None:
        fmt = "docx"
    fmt = fmt if fmt in ("docx", "pdf", "since") else "docx"
    # The files carry the revision and date they are issued as.
    issued_row = dict(row, revision=revision, issue_date=fields["issue_date"])
    data, name, mime = _bundle(issued_row, sections, "docx" if fmt == "since" else fmt, since)
    issue_id = review.record_issue(issued_row, fields, fmt, name, mime, data, ready["words"])
    store.set_revision(set_id, revision, fields["issue_date"])
    flash(Markup("Issued Rev {rev}. <a href=\"{url}\">Download the files as issued</a>.").format(
        rev=revision, url=url_for("specs.issue_file", set_id=set_id, issue_id=issue_id)), "success")
    return redirect(back + f"#issue-{issue_id}")


@bp.get("/sets/<int:set_id>/issues/<int:issue_id>/file")
@login_required
def issue_file(set_id: int, issue_id: int):
    _set_or_404(set_id)
    found = review.issue(set_id, issue_id, content=True)
    if found is None or not found.get("content"):
        abort(404)
    return Response(found["content"], mimetype=found["mime"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{found["filename"]}"'})


# --- changes since an issue ------------------------------------------------------------------

def _since(set_id: int) -> dict | None:
    issue_id = request.args.get("since", type=int)
    return review.issue(set_id, issue_id) if issue_id else review.last_issue(set_id)


@bp.get("/sets/<int:set_id>/changes")
@login_required
def changes(set_id: int):
    row = _set_or_404(set_id)
    since = _since(set_id)
    if since is None:
        flash("Nothing has been issued yet, so there is nothing to compare with.", "notice")
        return redirect(url_for("specs.issues", set_id=set_id))
    found = review.changes_since(since["snapshot"].get("sections", []), review.issued_words(row))
    answers = [h for h in review.history(set_id, kind="answer", since=since["history_mark"], most=500)]
    return render_template("specs/changes.html", spec=row, since=since, found=found, answers=answers,
                           issues=review.issues(set_id))


@bp.get("/sets/<int:set_id>/changes/docx")
@login_required
def changes_docx(set_id: int):
    row = _set_or_404(set_id)
    since = _since(set_id)
    sections = store.set_sections(set_id)
    if since is None or not sections:
        abort(404)
    data, name, mime = _bundle(row, sections, "docx", since)
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- comments --------------------------------------------------------------------------------

@bp.get("/sets/<int:set_id>/comments")
@login_required
def comments(set_id: int):
    row = _set_or_404(set_id)
    shown = request.args.get("show", "open")
    threads = review.comments(set_id, state=None if shown == "all" else shown)
    sections = {s["id"]: s for s in store.set_sections(set_id)}
    return render_template("specs/comments.html", spec=row, threads=threads, shown=shown,
                           sections=sections, open_n=review.open_comments(set_id),
                           may_close=lambda c: review.may_close(row, c))


@bp.post("/sets/<int:set_id>/comments")
@login_required
def add_comment(set_id: int):
    row = _set_or_404(set_id)
    back = _safe(request.form.get("back") or url_for("specs.comments", set_id=set_id), set_id)
    try:
        comment_id = review.add_comment(row, request.form.get("body", ""),
                                        request.form.get("row_id", type=int),
                                        request.form.get("node_id", ""),
                                        request.form.get("parent_id", type=int))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(back)
    flash("Reply added." if request.form.get("parent_id") else "Comment added.", "success")
    return redirect(back.split("#")[0] + f"#c-{comment_id}")


def _close(set_id: int, comment_id: int, open_again: bool):
    row = _set_or_404(set_id)
    back = _safe(request.form.get("back") or url_for("specs.comments", set_id=set_id), set_id)
    try:
        review.close_comment(row, comment_id, open_again)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash("Opened again." if open_again else "Closed.", "success")
    return redirect(back.split("#")[0] + f"#c-{comment_id}")


@bp.post("/sets/<int:set_id>/comments/<int:comment_id>/close")
@login_required
def close_comment(set_id: int, comment_id: int):
    return _close(set_id, comment_id, False)


@bp.post("/sets/<int:set_id>/comments/<int:comment_id>/reopen")
@login_required
def reopen_comment(set_id: int, comment_id: int):
    return _close(set_id, comment_id, True)


# --- history --------------------------------------------------------------------------------

@bp.get("/sets/<int:set_id>/history")
@login_required
def history(set_id: int):
    row = _set_or_404(set_id)
    row_id = request.args.get("section", type=int)
    kind = request.args.get("kind", "")
    who = request.args.get("who", "")
    before_id = request.args.get("before", type=int)
    rows = review.history(set_id, row_id=row_id, kind=kind if kind in review.KIND_NAMES else "",
                          who=who, before_id=before_id, most=201)
    more = len(rows) > 200
    return render_template(
        "specs/history.html", spec=row, rows=rows[:200], more=more, kind=kind, who=who,
        row_id=row_id, sections=store.set_sections(set_id), people=review.history_people(set_id),
        KIND_NAMES=review.KIND_NAMES)
