"""A project's trades: the tabs between its trades' specifications, and adding
another trade to a project. The routes join the THEMIS blueprint."""

from __future__ import annotations

from flask import flash, g, redirect, request, url_for

from .. import specs, specs_trades
from .. import specs_review as review
from ..auth import login_required
from .specs_views import _set_or_404, bp


# The pages another trade's engineer opens on a specification not of their
# trade: the IDC they were sent, and the questions asked of their team.
IDC_PAGES = {"specs.idc_page", "specs.idc_section", "specs.idc_propose", "specs.idc_decide"}
ASK_PAGES = {"specs.ask_page", "specs.ask_answer", "specs.explain"}


@bp.before_request
def _trade_wall():
    """An engineer sees their own trade's specifications only (an
    administrator sees every one): another trade's is opened only for the IDC
    sent to them, or for a question asked of their team."""
    set_id = (request.view_args or {}).get("set_id")
    user = g.get("user")
    if not set_id or user is None or specs_trades.sees_all(user):
        return None
    from .. import specs_store as store

    row = store.spec_set(set_id)
    if row is None or specs_trades.may_see(row, user):
        return None
    if request.endpoint in IDC_PAGES and _in_idc(row, user):
        return None
    if request.endpoint in ASK_PAGES and _team_asked(row, user):
        return None
    flash(f"{row['name']}'s {specs_trades.name(specs_trades.clean(row.get('trade'))).lower()} specification "
          f"is for its own trade's engineers. Ask its lead to add you to its team if you need it.", "error")
    return redirect(url_for("specs.index"))


def _in_idc(row, user) -> bool:
    from .. import specs_idc
    from ..db import query_one

    if specs_idc.may_propose(row, specs_idc.open_idc(row["id"]), user):
        return True
    # Their own input stays theirs to read once the IDC is closed.
    return query_one("SELECT 1 FROM spec_idc_changes WHERE set_id = ? AND by_user = ?",
                     (row["id"], user["id"])) is not None


def _team_asked(row, user) -> bool:
    from .. import specs_asks
    from ..db import query_one

    team = specs_asks.of_user(user)
    return bool(team) and query_one("SELECT 1 FROM spec_asks WHERE set_id = ? AND team = ?",
                                    (row["id"], team)) is not None


@bp.app_template_global("themis_may_see")
def themis_may_see(set_id: int) -> bool:
    return set_id not in specs_trades.hidden_ids(g.get("user"))


@bp.app_template_global("themis_trade_tabs")
def themis_trade_tabs(spec) -> list[dict]:
    try:
        return specs_trades.tabs(spec)
    except Exception:                      # a page of a project being deleted
        return []


@bp.app_template_global("themis_trade_name")
def themis_trade_name(code: str) -> str:
    return specs_trades.name(code)


@bp.app_template_global("themis_trades")
def themis_trades() -> list[dict]:
    return specs_trades.choices()


@bp.post("/sets/<int:set_id>/trades")
@login_required
def add_trade(set_id: int):
    """Another trade's specification of this project, led by whoever is chosen."""
    row = _set_or_404(set_id)
    if not review.may(row, g.user, "edit"):
        flash("Only the project's team adds a trade to it.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    trade = specs_trades.clean(request.form.get("trade"))
    lead = request.form.get("lead", type=int)
    try:
        new_id = specs_trades.add_trade(row, trade, lead_id=lead if lead and lead != g.user["id"] else None)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    who = specs_trades.user_name(lead) if lead and lead != g.user["id"] else "you"
    flash(f"Added the {specs_trades.name(trade).lower()} specification of {row['name']}, led by {who}. "
          "Its brief starts with the answers the trades share.", "success")
    return redirect(url_for("specs.story", set_id=new_id) + "#level-1")


@bp.app_template_global("themis_trade_leads")
def themis_trade_leads(code: str) -> list[dict]:
    return specs_trades.lead_choices().get(code, [])


@bp.app_template_global("themis_called_for")
def themis_called_for(spec) -> list[dict]:
    """What the project's other trades have said that this specification has
    not followed yet."""
    try:
        return specs_trades.called_for(spec)
    except Exception:
        return []
