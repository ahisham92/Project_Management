"""A project's trades: the tabs between its trades' specifications, and adding
another trade to a project. The routes join the THEMIS blueprint."""

from __future__ import annotations

from flask import flash, g, redirect, request, url_for

from .. import specs, specs_trades
from .. import specs_review as review
from ..auth import login_required
from .specs_views import _set_or_404, bp


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
