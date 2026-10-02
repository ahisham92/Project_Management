"""THEMIS's start page as a dashboard (the projects on a map, the counts that
matter), a page of its own to start a new project, .themis files in and out,
and the engineer's answer to each project answer the library has nothing
written for. The routes join the THEMIS blueprint."""

from __future__ import annotations

from collections import Counter

from flask import Response, flash, g, jsonify, redirect, render_template, request, url_for

from .. import specs, specs_places
from .. import specs_review as review
from .. import specs_store as store
from .. import specs_transfer as transfer
from ..auth import login_required
from ..db import query
from .specs_views import _is_admin, _set_or_404, _uploads, bp


def dashboard(everything: list[dict], mine: list[dict]) -> dict:
    """What the start page shows above the project lists."""
    mine_ids = {s["id"] for s in mine}
    issued = {r["set_id"]: r for r in query(
        "SELECT set_id, MAX(issued_at) AS last, COUNT(*) AS n FROM spec_issues GROUP BY set_id")}
    points, unplaced = [], []
    for s in everything:
        city, country = store.place_of(s)
        lat, lng = s.get("lat"), s.get("lng")
        if lat is None and (city or country):
            found = specs_places.locate(city, country)
            if found:
                lat, lng = found[0], found[1]
        one = {"id": s["id"], "name": s["name"], "package": s.get("package") or "",
               "code": s["code"], "family": s["family"], "client": s["client"], "city": city,
               "country": country, "lat": lat, "lng": lng, "mine": s["id"] in mine_ids,
               "revision": s["revision"], "issued": bool(issued.get(s["id"])),
               "url": url_for("specs.spec_set", set_id=s["id"])}
        if lat is not None:
            points.append(one)
        elif city or country:
            unplaced.append(one)        # the browser looks these up
    recent = [dict(r) for r in query(
        "SELECT i.id, i.set_id, i.revision, i.purpose, i.issue_date, i.issued_by, s.name, s.package "
        "FROM spec_issues i JOIN spec_sets s ON s.id = i.set_id ORDER BY i.issued_at DESC LIMIT 60")]
    from .. import specs_trades
    recent = specs_trades.visible(recent, g.get("user"), key="set_id")[:6]
    countries = Counter(c for c in (store.place_of(s)[1] for s in everything) if c)
    return {
        "points": points, "unplaced": unplaced, "recent": recent,
        "stats": {
            "projects": len(everything), "mine": len(mine),
            "issued": sum(1 for s in everything if s["id"] in issued),
            "issues": sum(r["n"] for r in issued.values()),
            "countries": len(countries),
            "families": Counter(s["family"] for s in everything),
            "unplaced": sum(1 for s in everything if not any(store.place_of(s))),
        },
        "issued_ids": set(issued),
    }


@bp.get("/new")
@login_required
def new_project():
    from .. import specs_trades as _trades

    everything = _trades.visible(store.sets(), g.user)
    on = review.my_sets(g.user)
    mine = [s for s in everything if s["created_by"] == g.user["id"] or s["id"] in on]
    start_from = request.args.get("start_from", type=int)
    source = store.spec_set(start_from) if start_from else None
    from .. import specs_trades

    return render_template(
        "specs/new.html", families=store.families(), mine=mine,
        others=[s for s in everything if s not in mine], start_from=start_from, source=source,
        place=store.place_of(source) if source else ("", ""), library=store.library(),
        countries=specs_places.country_names(), is_admin=_is_admin(),
        trades=specs_trades.choices(), my_trade=specs_trades.of_user(g.user),
        leads=specs_trades.lead_choices(),
        trade_families={t: {f["code"]: f["sections"] for f in store.families(t)} for t in specs_trades.CODES})


@bp.get("/sets/<int:set_id>/themis")
@login_required
def export_themis(set_id: int):
    _set_or_404(set_id)
    data, name = transfer.export(set_id, template=request.args.get("template") == "1")
    return Response(data, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_project():
    if request.method == "GET":
        return render_template("specs/import.html", countries=specs_places.country_names())
    files = _uploads("file", transfer.MOST)
    if not files:
        flash("Choose a .themis file to import.", "error")
        return redirect(url_for("specs.import_project"))
    filename, data = files[0]
    try:
        set_id, got = transfer.import_file(data, request.form)
    except specs.SpecError as exc:
        flash(f"{filename}: {exc}", "error")
        return redirect(url_for("specs.import_project"))
    what = "template" if got["kind"] == "template" else "project"
    flash(f"Imported the {what} {filename}"
          + (f" (sent by {got['by']}, {got['at']})" if got["by"] else "")
          + f": {got['sections']} section{'s' if got['sections'] != 1 else ''}"
          + (f", {got['own']} with no master of the same number here, kept as the project's own"
             if got["own"] else "")
          + ". It is yours to edit; check its answers and sections before you issue it.", "success")
    return redirect(url_for("specs.spec_set", set_id=set_id))


@bp.post("/sets/<int:set_id>/cover")
@login_required
def cover_answer(set_id: int):
    """One answer the library has nothing written for, settled by the engineer:
    a section already in covers it, a section of the project's own is written
    for it, or the project does not need one. Or opened again."""
    _set_or_404(set_id)
    f = request.form
    key, value, how = f.get("key", ""), f.get("value", ""), f.get("how", "")
    back = url_for("specs.spec_set", set_id=set_id) + "#step-sections"
    if how == "own":
        number = " ".join(f.get("number", "").split())
        if not number:
            flash("Give the new section a number.", "error")
            return redirect(back)
        try:
            row_id = store.new_own_section(set_id, number, f.get("title", "").strip() or f"{value}".upper())
        except specs.SpecError as exc:
            flash(str(exc), "error")
            return redirect(back)
        store.set_cover(set_id, key, value, "own", number)
        flash(f"Section {number} started for {value}: write what the project needs in it.", "success")
        return redirect(url_for("specs.edit_set_section", set_id=set_id, row_id=row_id))
    if how == "section" and not f.get("section"):
        flash("Pick the section that covers it.", "error")
        return redirect(back)
    store.set_cover(set_id, key, value, how if how in store.COVER_HOW else None,
                    f.get("section", ""), f.get("note", ""))
    flash({"section": f"Marked {value} as covered by {f.get('section', '')}.",
           "not_needed": f"Marked {value} as not needing a section of its own.",
           }.get(how, f"{value} is open again."), "success")
    return redirect(back)


@bp.post("/points")
@login_required
def save_points():
    """Points the browser found for cities the site's own list does not have,
    kept so the map does not look them up again. Only a project with no point
    yet takes one."""
    saved = 0
    for one in (request.get_json(silent=True) or {}).get("points", [])[:50]:
        try:
            set_id, lat, lng = int(one["id"]), float(one["lat"]), float(one["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        row = store.spec_set(set_id)
        if row and row.get("lat") is None and -90 <= lat <= 90 and -180 <= lng <= 180:
            store.set_point(set_id, lat, lng)
            saved += 1
    return jsonify(saved=saved)
