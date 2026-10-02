"""IDC pages: one trade's specification sent to the project's other trades,
their input on it as tracked changes, and the specification's engineers
accepting or rejecting each. The routes join the THEMIS blueprint."""

from __future__ import annotations

from flask import abort, flash, g, redirect, render_template, request, url_for

from .. import specs, specs_idc, specs_trades
from .. import specs_review as review
from .. import specs_store as store
from ..auth import login_required
from .specs_review_views import SELF_CHECKED
from .specs_views import _set_or_404, bp

# The other trades' engineers put their input in on a specification they may
# not change: these routes decide for themselves who may use them.
SELF_CHECKED.update({"specs.idc_propose", "specs.idc_decide"})


@bp.app_template_global("themis_idc")
def themis_idc(spec) -> dict | None:
    """The open IDC of a specification, for its pages' banners."""
    try:
        return specs_idc.open_idc(spec["id"])
    except Exception:                      # a page of a project being deleted
        return None


@bp.app_template_global("themis_idc_of_project")
def themis_idc_of_project(spec) -> list[dict]:
    """The open IDCs of the project's other trades' specifications that this
    one's trade is asked for input on."""
    try:
        mine = specs_trades.clean(spec.get("trade"))
        out = []
        for s in specs_trades.siblings(spec):
            if s["id"] == spec["id"]:
                continue
            it = specs_idc.open_idc(s["id"])
            if it and mine in it["trade_list"]:
                it["of"] = s
                it["of_trade"] = specs_trades.name(specs_trades.clean(s.get("trade")))
                out.append(it)
        return out
    except Exception:
        return []


@bp.post("/sets/<int:set_id>/idc")
@login_required
def send_idc(set_id: int):
    row = _set_or_404(set_id)
    if not specs_idc.may_decide(row, g.user):
        flash("Only the specification's team sends an IDC of it.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    try:
        specs_idc.send(row, request.form.getlist("trade"), request.form.get("note", ""), g.user)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    it = specs_idc.open_idc(set_id)
    flash(f"IDC sent to {', '.join(it['trade_names'])}. Their engineers see it on their specification of "
          "the project and on their THEMIS start page, and put their input in as tracked changes for you "
          "to accept or reject.", "success")
    return redirect(url_for("specs.idc_page", set_id=set_id))


@bp.get("/sets/<int:set_id>/idc")
@login_required
def idc_page(set_id: int):
    row = _set_or_404(set_id)
    it = specs_idc.open_idc(set_id)
    history = specs_idc.idcs(set_id)
    if it is None and not history:
        flash("No IDC of this specification yet: send one from the project page.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    shown = it or history[0]
    counts = specs_idc.by_section(shown["id"])
    return render_template(
        "specs/idc.html", spec=row, it=shown, history=history, sections=store.set_sections(set_id),
        counts=counts, may_decide=specs_idc.may_decide(row, g.user),
        may_propose=specs_idc.may_propose(row, it, g.user), between=specs_idc.between(row) if it else [],
        changes=specs_idc.changes(shown["id"]), to=specs_idc.to_trades(row))


@bp.get("/sets/<int:set_id>/idc/<int:row_id>")
@login_required
def idc_section(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    section = store.set_section(set_id, row_id)
    history = specs_idc.idcs(set_id)
    if section is None or not history:
        abort(404)
    it = specs_idc.open_idc(set_id) or history[0]
    found = specs_idc.changes(it["id"], row_id)
    by_node: dict[str, list[dict]] = {}
    for c in found:
        by_node.setdefault(c["node_id"], []).append(c)
    sections = store.set_sections(set_id)
    ids = [s["id"] for s in sections]
    at = ids.index(row_id) if row_id in ids else 0
    return render_template(
        "specs/idc_section.html", spec=row, it=it, section=section,
        paragraphs=specs_idc.words_of(row, section), by_node=by_node, found=found,
        may_decide=specs_idc.may_decide(row, g.user), may_propose=specs_idc.may_propose(row, it, g.user),
        prev=sections[at - 1] if at > 0 else None, next=sections[at + 1] if at + 1 < len(sections) else None,
        counts=specs_idc.by_section(it["id"]), levels=[(k, specs.MARK.get(k, k)) for k in specs.KINDS
                                                         if k not in (specs.NOTE, "TBL")])


@bp.post("/sets/<int:set_id>/idc/<int:row_id>/propose")
@login_required
def idc_propose(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    it = specs_idc.open_idc(set_id)
    back = url_for("specs.idc_section", set_id=set_id, row_id=row_id)
    node_id = request.form.get("node", "")
    if not specs_idc.may_propose(row, it, g.user):
        flash("Only the engineers of a trade the IDC went to put input in, while it is open.", "error")
        return redirect(back)
    try:
        specs_idc.propose(row, it, row_id, node_id, request.form.get("kind", ""),
                          request.form.get("text", ""), request.form.get("why", ""), g.user,
                          level=request.form.get("level", ""))
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash("Change put in, marked as yours, for the specification's engineers to accept or reject.",
              "success")
    return redirect(back + f"#p-{node_id}")


@bp.post("/sets/<int:set_id>/idc/changes/<int:change_id>")
@login_required
def idc_decide(set_id: int, change_id: int):
    row = _set_or_404(set_id)
    c = specs_idc.change(change_id)
    if c is None or c["set_id"] != set_id:
        abort(404)
    back = request.form.get("back") or url_for("specs.idc_section", set_id=set_id, row_id=c["row_id"])
    if not back.startswith("/"):
        back = url_for("specs.idc_section", set_id=set_id, row_id=c["row_id"])
    how = request.form.get("how", "")
    try:
        if how == "withdraw":
            specs_idc.withdraw(change_id, g.user)
            flash("Your change is taken back.", "success")
        elif how in ("accept", "reject"):
            if not specs_idc.may_decide(row, g.user):
                raise specs.SpecError("Only the specification's own team accepts or rejects a change.")
            if how == "reject" and not request.form.get("answer", "").strip():
                raise specs.SpecError("Say why it is rejected: the answer goes back to "
                                      f"{c['by_name']}.")
            done = specs_idc.decide(row, change_id, how == "accept", request.form.get("answer", ""), g.user)
            flash(("Accepted: the section now reads as proposed." if how == "accept" else
                   f"Rejected, with your answer to {c['by_name']}.")
                  + (" The paragraph had changed since the change was put in: check how it reads now."
                     if done["stale"] else ""), "success")
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return redirect(back + f"#p-{c['node_id']}")


@bp.post("/sets/<int:set_id>/idc/<int:row_id>/accept-all")
@login_required
def idc_accept_all(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    it = specs_idc.open_idc(set_id)
    back = url_for("specs.idc_section", set_id=set_id, row_id=row_id)
    if not it or not specs_idc.may_decide(row, g.user):
        flash("Only the specification's own team accepts changes, while the IDC is open.", "error")
        return redirect(back)
    done, skipped = 0, 0
    for c in specs_idc.changes(it["id"], row_id):
        if c["state"] != "open":
            continue
        try:
            specs_idc.decide(row, c["id"], True, "", g.user)
            done += 1
        except specs.SpecError:
            skipped += 1
    flash(f"Accepted {done} change{'s' if done != 1 else ''}."
          + (f" {skipped} could not go in (the paragraph is gone): reject them." if skipped else ""),
          "success" if done else "error")
    return redirect(back)


@bp.post("/sets/<int:set_id>/idc/close")
@login_required
def idc_close(set_id: int):
    row = _set_or_404(set_id)
    it = specs_idc.open_idc(set_id)
    if not it or not specs_idc.may_decide(row, g.user):
        flash("Only the specification's own team closes its IDC.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    specs_idc.close(row, it, g.user)
    flash("IDC closed." + (f" {it['open']} change{'s were' if it['open'] != 1 else ' was'} left undecided "
                           "and stay on its record." if it["open"] else ""), "success")
    return redirect(url_for("specs.spec_set", set_id=set_id))
