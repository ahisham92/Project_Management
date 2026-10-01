"""The issued specifications across projects, the amendments projects made to
the MTD for an administrator to judge, and the standards register. The routes
join the THEMIS blueprint."""

from __future__ import annotations

from flask import Response, abort, flash, redirect, render_template, request, url_for

from .. import specs
from .. import specs_issued as issued
from .. import specs_store as store
from ..auth import login_required
from .specs_views import _admin_only, _is_admin, bp


# --- the issued specifications ----------------------------------------------------------------

@bp.get("/issued")
@login_required
def issued_list():
    """Every specification the office has issued, with where and for whom,
    kept when the project itself is gone."""
    family = request.args.get("family", "")
    search = request.args.get("q", "")
    latest = request.args.get("all") != "1"
    rows = issued.records(family=family, search=search, latest=latest)
    return render_template("specs/issued.html", rows=rows, family=family, search=search, latest=latest,
                           families=store.families(), every=issued.records(),
                           is_admin=_is_admin())


@bp.get("/issued/compare")
@login_required
def issued_compare():
    a, b = issued.record(request.args.get("a", type=int) or 0), issued.record(request.args.get("b", type=int) or 0)
    if a is None or b is None:
        flash("Pick two issues to compare.", "error")
        return redirect(url_for("specs.issued_list"))
    return render_template("specs/issued_compare.html", a=a, b=b, found=issued.compare(a, b),
                           every=issued.records())


@bp.get("/issued/answers")
@login_required
def issued_answers():
    """How each project answered every question, as last issued."""
    family = request.args.get("family", "")
    table = issued.answers_table(family)
    if request.args.get("format") == "csv":
        return Response(issued.answers_csv(table), mimetype="text/csv", headers={
            "Content-Disposition": f"attachment; filename=THEMIS answers {family or 'all'}.csv"})
    return render_template("specs/issued_answers.html", table=table, family=family,
                           families=store.families(),
                           only_differ=request.args.get("differ") == "1")


@bp.get("/issued/<int:record_id>/file")
@login_required
def issued_file(record_id: int):
    r = issued.record(record_id)
    if r is None:
        abort(404)
    if not (r["alive"] and r["has_files"]):
        flash("The files went with the project when it was deleted; its words and data are kept here.",
              "error")
        return redirect(url_for("specs.issued_list"))
    return redirect(url_for("specs.issue_file", set_id=r["set_id"], issue_id=r["issue_id"]))


# --- amendments from projects, for the MTD -----------------------------------------------------

def _amendment_args() -> tuple:
    f = request.form
    return (f.get("family", ""), f.get("number", ""), f.get("node_id", ""), f.get("set_id", type=int) or 0,
            f.get("record_id", type=int) or None)


def _back_to_amendments():
    back = request.form.get("back", "")
    return redirect(back if back.startswith("/specs/") else url_for("specs.from_projects"))


@bp.get("/library/amendments")
@login_required
def from_projects():
    """The amendments projects made to the MTD, for an administrator to write
    into it or leave as the project's own."""
    if not _is_admin():
        flash("Only an administrator reviews amendments for the MTD.", "error")
        return redirect(url_for("specs.library"))
    family = request.args.get("family", "")
    live = request.args.get("source") == "live"
    decided = request.args.get("decided") == "1"
    found = issued.from_projects(family, live=live, show_decided=decided)
    return render_template("specs/from_projects.html", found=found, family=family, live=live,
                           decided=decided, families=store.families())


@bp.post("/library/amendments/adopt")
@login_required
def adopt_amendment():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    family, number, node_id, set_id, record_id = _amendment_args()
    text = request.form.get("text")
    try:
        version = issued.adopt(family, number, node_id, set_id, record_id,
                               text=text if text and text.strip() else None)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return _back_to_amendments()
    flash(f"Written into the MTD: section {number} ({family}) is now version {version}. Projects that "
          "took it are offered the new version on their section page.", "success")
    return _back_to_amendments()


@bp.post("/library/amendments/keep")
@login_required
def keep_amendment():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    family, number, node_id, set_id, record_id = _amendment_args()
    try:
        issued.keep_out(family, number, node_id, set_id, record_id, request.form.get("note", ""))
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return _back_to_amendments()


@bp.post("/library/amendments/reopen")
@login_required
def reopen_amendment():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    family, number, node_id, set_id, _ = _amendment_args()
    issued.reopen(family, number, node_id, set_id)
    return _back_to_amendments()


# --- the standards register --------------------------------------------------------------------

@bp.get("/standards/register")
@login_required
def standards_register():
    """Every standard the MTD and the projects cite, with its current edition
    as last checked."""
    show = request.args.get("show", "attention")
    rows = issued.register(show)
    return render_template("specs/register.html", rows=rows, show=show, is_admin=_is_admin(),
                           counts=_counts(issued.register("all")), statuses=issued.STATUSES)


def _counts(rows: list[dict]) -> dict:
    out = {"all": len(rows), "stale": sum(r["stale"] for r in rows)}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


@bp.get("/standards/register.csv")
@login_required
def standards_register_csv():
    return Response(issued.register_csv(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=THEMIS standards to check.csv"})


@bp.post("/standards/register/load")
@login_required
def load_standards_check():
    """A check of current editions read in and shown for an administrator to
    tick what the register takes."""
    if not _admin_only():
        return redirect(url_for("specs.standards_register"))
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose the check file (.csv) to load.", "error")
        return redirect(url_for("specs.standards_register"))
    try:
        rows = issued.read_check(upload.read())
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.standards_register"))
    return render_template("specs/register_load.html", rows=issued.preview(rows),
                           filename=upload.filename)


@bp.post("/standards/register/apply")
@login_required
def apply_standards_check():
    if not _admin_only():
        return redirect(url_for("specs.standards_register"))
    take = set(request.form.getlist("take"))
    rows = [r for r in issued.as_rows(request.form.get("rows", "")) if r["key"] in take]
    n = issued.apply_check(rows)
    flash(f"The register took {n} standard{'s' if n != 1 else ''}. The check now flags every citation "
          "of an older edition or a withdrawn standard, for the engineer to decide.", "success")
    return redirect(url_for("specs.standards_register"))


@bp.post("/standards/register/one")
@login_required
def save_standard_status():
    if not _admin_only():
        return redirect(url_for("specs.standards_register"))
    key = request.form.get("key", "")
    if not key:
        abort(400)
    issued.save_status(key, request.form)
    flash(f"Saved {request.form.get('standard') or key} in the register.", "success")
    return redirect(url_for("specs.standards_register", show=request.form.get("show", "attention"))
                    + f"#std-{key}")
