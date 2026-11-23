"""A project's Procedures tab and its "Needs attention" view.

Both hang off the project blueprint, so they sit among the project's own tabs
and share its sign-in, its roles and its look.
"""

from __future__ import annotations

from flask import Response, g, jsonify, render_template, request, url_for

from .. import attention, procedures
from ..auth import ROLE_RANK, load_project, login_required
from ..service import project_snapshot, today
from .projects_views import _params, bp


def _can_report(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["member"]


@bp.get("/procedures", endpoint="procedures")
@login_required
def procedures_page(project_id: int):
    project, role = load_project(project_id)
    return render_template("procedures.html", project=project, role=role,
                           library=procedures.library())


@bp.get("/procedures/app")
@login_required
def procedures_app(project_id: int):
    """The journey itself, shown inside the tab."""
    project, role = load_project(project_id)
    server = {
        "state": procedures.load_state(project),
        "saveUrl": url_for("projects.procedures_save", project_id=project_id),
        "stateUrl": url_for("projects.procedures_state", project_id=project_id),
        "canEdit": _can_report(role),
        "project": {"code": project["code"], "name": project["name"]},
    }
    return Response(procedures.page_html(server), mimetype="text/html")


@bp.get("/procedures/state")
@login_required
def procedures_state(project_id: int):
    project, _ = load_project(project_id)
    return jsonify(procedures.load_state(project))


@bp.post("/procedures/save")
@login_required
def procedures_save(project_id: int):
    project, role = load_project(project_id)
    if not _can_report(role):
        return jsonify({"ok": False, "error": "You can view this project but not change it."}), 403
    patch = request.get_json(silent=True)
    state = procedures.load_state(project)
    try:
        procedures.apply_patch(state, (patch or {}).get("patch") or {})
    except procedures.PatchError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    procedures.save_state(project_id, state, g.user["id"])
    return jsonify({"ok": True, "state": state})


@bp.get("/attention", endpoint="attention")
@login_required
def attention_view(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    items = attention.gather(project, snapshot)
    return render_template("attention.html", project=project, role=role,
                           lanes=attention.lanes(items), items=items, data_date=data_date,
                           today=today())
