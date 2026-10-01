"""Packages of one project, as pages: the other packages, and each difference
from what they issued, for the package's team to accept or keep. The routes
join the THEMIS blueprint."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for

from .. import specs
from .. import specs_packages as packages
from .. import specs_review as review
from ..auth import login_required
from .specs_views import _set_or_404, bp


@bp.get("/sets/<int:set_id>/packages")
@login_required
def project_packages(set_id: int):
    row = _set_or_404(set_id)
    found = packages.discrepancies(row)
    return render_template("specs/packages.html", spec=row, found=found,
                           package=packages.package_name(row), owner=review.owner_name(row),
                           may_edit=review.may(row, g.user, "edit"),
                           show_kept=request.args.get("kept") == "1")


def _which() -> tuple:
    f = request.form
    return (f.get("peer", type=int) or 0, f.get("kind", ""), f.get("number", ""), f.get("key", ""))


def _back(set_id: int):
    anchor = request.form.get("anchor", "")
    return redirect(url_for("specs.project_packages", set_id=set_id) + (f"#{anchor}" if anchor else ""))


@bp.post("/sets/<int:set_id>/packages/accept")
@login_required
def accept_package_difference(set_id: int):
    row = _set_or_404(set_id)
    try:
        flash(packages.accept(row, *_which()), "success")
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return _back(set_id)


@bp.post("/sets/<int:set_id>/packages/keep")
@login_required
def keep_package_difference(set_id: int):
    row = _set_or_404(set_id)
    try:
        packages.reject(row, *_which(), note=request.form.get("note", ""))
        flash("Kept as this package has it. The difference is no longer flagged unless either "
              "wording changes.", "success")
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return _back(set_id)


@bp.post("/sets/<int:set_id>/packages/reopen")
@login_required
def reopen_package_difference(set_id: int):
    _set_or_404(set_id)
    packages.reopen(set_id, *_which())
    return _back(set_id)
