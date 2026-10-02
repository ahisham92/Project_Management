"""The specification writer, as pages.

Two places. **The library** is the office's master text of every section, the
one the administrator keeps: sections come into it from Word, are edited as
text, and every save is kept as a version. **A specification** is one
project's: its header and document code, the choices that switch paragraphs in
and out, the words it fills in, and its own copy of each section — amended
freely, compared paragraph by paragraph with the master it came from, and
issued in the house template so it looks like every other one.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

from flask import (
    Blueprint, Response, abort, flash, g, get_flashed_messages, jsonify, redirect, render_template,
    request, url_for,
)
from markupsafe import Markup, escape

from .. import specs, specs_check, specs_export, specs_places, specs_questions, specs_review as review, specs_seed
from .. import specs_store as store
from ..specs_inputs import DECIDED
from ..auth import login_required

bp = Blueprint("specs", __name__, url_prefix="/specs")

# A specification section is a few hundred kilobytes; a house template with a
# logo in its header a few more. Twelve megabytes is room for a batch of them.
MOST = 12 * 1024 * 1024
# An IFC export of a whole model is bigger: a large one runs to tens of megabytes.
MOST_MODEL = 80 * 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@bp.app_template_filter("spectext")
def spectext(text: str, values: dict | None = None, reader=None, here: str = "") -> Markup:
    """A paragraph as it reads for the project: each filled-in word marked,
    each cross-reference written out as it stands now, and — given a reader
    that knows the project's basis — each standard on that basis."""
    values = values or {}
    text = text or ""
    if specs.INLINE.search(text):
        # Choices inside the paragraph: each marked, and shown only when it holds.
        out, last = [], 0
        for match in specs.INLINE.finditer(text):
            out.append(spectext(text[last:match.start()], values, reader, here))
            condition = f"{match.group(1)}{match.group(2)}{match.group(3)}"
            holds = reader is None or specs.applies(condition, getattr(reader, "chosen", {}))
            if holds:
                out.append(Markup('<span class="spec-choice" title="Only when %s">%s</span>')
                           % (condition, spectext(match.group(4), values, reader, here)))
            last = match.end()
        out.append(spectext(text[last:], values, reader, here))
        return Markup("").join(out)
    out, last = [], 0
    for match in specs_check.REF.finditer(text):
        out.append(_words(text[last:match.start()], values, reader))
        if reader is None:
            out.append(Markup('<span class="spec-ref">%s</span>') % match.group(0))
        else:
            shown, problem = reader.ref(match.group(1), here)
            out.append(Markup('<span class="spec-ref%s" title="%s">%s</span>')
                       % (" spec-bad" if problem else "",
                          problem or f"{match.group(0)}: kept up to date", shown))
        last = match.end()
    out.append(_words(text[last:], values, reader))
    return Markup("").join(out)


def _words(text: str, values: dict, reader) -> Markup:
    if reader is not None:
        text = reader.standards(text)
    out, last = [], 0
    for match in specs.VARIABLE.finditer(text):
        out.append(_open(text[last:match.start()]))
        name = match.group(1)
        if match.group(3) is not None:
            # A question from the master: its answer, or the master's words
            # with their choices marked until it has one.
            said = specs.answer(match, values or {})
            if said is None:
                out.append(Markup('<span class="spec-ask" title="A question not answered yet">%s</span>')
                           % _open(match.group(3)))
            elif said:
                out.append(Markup('<span class="spec-var spec-answered" title="Answered: %s">%s</span>')
                           % (name, said))
        elif values.get(name):
            out.append(Markup('<span class="spec-var" title="{{%s}}">%s</span>')
                       % (name, values[name]))
        else:
            out.append(Markup('<span class="spec-var" title="No value yet">%s</span>')
                       % match.group(0))
        last = match.end()
    out.append(_open(text[last:]))
    return Markup("").join(out)


BRACKETED = re.compile(r"\[[^\[\]]{1,300}\]")


def _open(text: str) -> Markup:
    """Plain words, with each choice still left in square brackets marked."""
    out, last = [], 0
    for match in BRACKETED.finditer(text):
        out.append(escape(text[last:match.start()]))
        out.append(Markup('<span class="spec-open" title="A choice still to make">%s</span>')
                   % match.group(0))
        last = match.end()
    out.append(escape(text[last:]))
    return Markup("").join(out)


@bp.app_template_filter("spec_mark")
def spec_mark(text: str, words: str = "") -> Markup:
    """The text with the words a check item is about marked."""
    text = text or ""
    at = text.lower().find(words.lower()) if words else -1
    if at < 0:
        return escape(text)
    return (escape(text[:at]) + Markup('<mark class="spec-mark">%s</mark>') % text[at:at + len(words)]
            + escape(text[at + len(words):]))


@bp.app_template_test("spec_fits")
def spec_fits(section: dict, chosen: dict) -> bool:
    return store.fits(section.get("applies") or "", chosen or {})


@bp.app_template_test("spec_declined")
def spec_declined(section: dict, declined: set) -> bool:
    return section.get("id") in (declined or ())


@bp.app_template_filter("spec_icon_for")
def spec_icon_for(choice: str, key: str, icons: dict) -> str:
    return (icons or {}).get((key, choice), "")


@bp.app_template_filter("spec_applies")
def spec_applies(when: str, chosen: dict) -> bool:
    return (when or "").strip() == store.ALWAYS or specs.applies(when or "", chosen or {})


@bp.app_template_filter("spec_why")
def spec_why(when: str, family: str = "", opts: dict | None = None) -> str:
    """Why a section is in, in plain words rather than its condition."""
    return store.plain_condition(when, family, opts)


@bp.app_template_filter("spec_rows")
def spec_rows(text: str) -> list[list[str]]:
    return specs.rows_of(text)


def _rows(nodes: list[dict], chosen: dict, base: list[dict] | None) -> list[dict]:
    """What the section page lists: the project's paragraphs, numbered, and
    — where there is a master to compare with — the ones it dropped, in place."""
    numbered = {p["id"]: p for p in specs.number(nodes, chosen)}
    if base is None:
        return [dict(p, state="same", was=None) for p in numbered.values()]
    rows = []
    for m in specs.compare(base, nodes):
        if m["state"] == "removed":
            rows.append(dict(m, label="", included=True,
                             indent=max(specs.DEPTH.get(m["level"], 2) - 1, 0)))
        else:
            one = numbered[m["id"]]
            rows.append(dict(m, label=one["label"], included=one["included"], indent=one["indent"]))
    return rows


ID = re.compile(r"^[0-9a-f]{8}$")


def _edited_nodes(body: str) -> list[dict]:
    """The paragraphs the editor sent back. The page editor sends them as they
    are, with their ids, so nothing has to be matched up again; the plain text
    editor sends text, which is lined up against what was there."""
    before = specs.loads(body)
    sent = request.form.get("nodes", "")
    if sent and request.form.get("mode") != "text":
        try:
            data = json.loads(sent)
        except ValueError as exc:
            raise specs.SpecError("The editor sent something that could not be read; "
                                  "nothing was saved.") from exc
        # The editor says how many paragraphs it sent: a page cut short on the
        # way is refused rather than saved over the section.
        if isinstance(data, dict):
            data, count = data.get("nodes"), data.get("count")
            if not isinstance(data, list) or count != len(data):
                raise specs.SpecError("The page did not arrive whole; nothing was saved. "
                                      "Try saving again.")
        nodes, seen = [], set()
        for n in data if isinstance(data, list) else []:
            if not isinstance(n, dict) or n.get("level") not in specs.KINDS:
                continue
            text = str(n.get("text") or "").replace("\r", "")
            text = text if n["level"] == specs.TABLE else " ".join(text.split())
            if not text.strip():
                continue
            if n["level"] in ("PRT", "ART") and not specs.is_nbs(before):
                text = text.upper()
            ident = str(n.get("id") or "")
            ident = ident if ID.match(ident) and ident not in seen else None
            node = specs.node(n["level"], text, str(n.get("when") or "").strip(), ident)
            seen.add(node["id"])
            nodes.append(node)
        return nodes
    return specs.align(before, specs.from_text(request.form.get("text", "")))


def _editor(s: dict, family: str, library: bool, spec=None, seen: str = ""):
    """The edit page: the page editor, with the plain text beside it."""
    nodes = specs.loads(s["body"])
    sections = [{"number": x["number"], "title": specs_check.title_case(x["title"])}
                for x in store.library(family)]
    options, variables = store.options(), store.variables()
    return render_template(
        "specs/edit.html", spec=spec, section=s, text=specs.to_text(nodes),
        nodes=nodes, nbs=specs.is_nbs(nodes), sections=sections, options=options,
        variables=variables, library=library, seen=seen,
        options_json=[{"key": o["key"], "label": o["label"], "choices": o["choice_list"],
                       "group": o.get("grp") or ""} for o in options],
        variables_json=[{"key": v["key"], "label": v["label"]} for v in variables])


def _is_admin() -> bool:
    return g.user is not None and g.user["role"] == "admin"


def _admin_only() -> bool:
    if not _is_admin():
        flash("Only an administrator changes the master library.", "error")
        return False
    return True


def _set_or_404(set_id: int) -> dict:
    row = store.spec_set(set_id)
    if row is None:
        abort(404)
    return row


def _set_section_or_404(set_id: int, row_id: int) -> dict:
    row = store.set_section(set_id, row_id)
    if row is None:
        abort(404)
    return row


def _uploads(field: str, most: int = MOST) -> list[tuple[str, bytes]]:
    """The files sent, each read in full; anything too big is refused."""
    out = []
    for upload in request.files.getlist(field):
        if not upload or not upload.filename:
            continue
        data = upload.read(most + 1)
        if len(data) > most:
            flash(f"{upload.filename} is too big to read here — {most // (1024 * 1024)} MB is the "
                  "limit.", "error")
            continue
        out.append((upload.filename, data))
    return out


def _docx_response(data: bytes, name: str) -> Response:
    return Response(data, mimetype=DOCX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.after_request
def _progress_answer(response: Response) -> Response:
    """A form sent, or a file fetched, by spec-progress.js (which says so in
    the X-Specs-Progress header) is told where the server would have sent the
    page, as {"go": url}, instead of being redirected there: a redirect the
    browser followed inside the script would take the page's messages with
    it. Every file sent back says how big it is, so its progress can be shown."""
    if request.headers.get("X-Specs-Progress") and response.status_code in (301, 302, 303, 307, 308):
        return jsonify(go=response.location)
    if response.headers.get("Content-Disposition", "").startswith("attachment") \
            and "Content-Length" not in response.headers:
        size = response.calculate_content_length()
        if size is not None:
            response.headers["Content-Length"] = str(size)
    return response


# --- the front page -------------------------------------------------------------

@bp.get("/")
@login_required
def index():
    from .specs_home_views import dashboard

    everything = store.sets()
    on = review.my_sets(g.user)
    mine = [s for s in everything if s["created_by"] == g.user["id"] or s["id"] in on]
    if request.args.get("start_from"):
        # The old way into a copy ("Start a new package or project from this one").
        return redirect(url_for("specs.new_project", **request.args))
    return render_template("specs/index.html", sets=everything, mine=mine,
                           others=[s for s in everything if s not in mine],
                           families=store.families(), library=store.library(),
                           is_admin=_is_admin(), flagged=_flagged(mine), **dashboard(everything, mine))


def _package_source() -> dict | None:
    """Starting another package of a project: its name, code and client to begin with."""
    start_from = request.args.get("start_from", type=int)
    if not start_from or request.args.get("package") != "1":
        return None
    return store.spec_set(start_from)


def _flagged(rows) -> dict[int, int]:
    """For the user's own packages, the differences from the project's other
    issued packages they have not decided."""
    from .. import specs_packages as packages

    out = {}
    for one in rows:
        if packages.project_key(one["code"]):
            n = packages.open_count(one)
            if n:
                out[one["id"]] = n
    return out


@bp.post("/sets")
@login_required
def new_set():
    try:
        set_id = store.create_set(request.form, copy_from=request.form.get("copy_from", type=int))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.new_project", start_from=request.form.get("copy_from") or None))
    models = _uploads("model", MOST_MODEL)
    if models and _read_model(set_id, *models[0]):
        _added(set_id)
    if request.form.get("copy_from"):
        return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-elements")
    # A new project starts on the story: its brief, one question at a time,
    # on a bare plot that is built up as it is answered.
    return redirect(url_for("specs.story", set_id=set_id) + "#level-1")


def _added(set_id: int, before: set[int] | None = None) -> None:
    """The sections the answers call for, put in, and the engineer told which
    and why; and the ones in it that the answers have just ruled out, named
    with a button to take them out (they stay unless the engineer says so,
    since they may carry amendments). One already ruled out before this
    change is not named again."""
    done = store.auto_add(set_id)
    if done["added"]:
        flash(Markup("Added {n} section{s} the answers call for: {list}.").format(
            n=len(done["added"]), s="s" if len(done["added"]) != 1 else "",
            list=Markup("; ").join(Markup("<strong>{}</strong> {} ({})").format(
                x["number"], specs_check.title_case(x["title"]),
                "every project of this kind" if x["applies"] == store.ALWAYS else x["applies"])
                for x in done["added"])), "success")
    out = [x for x in done["out"] if x["id"] not in (before or set())]
    if out:
        one = len(out) == 1
        flash(Markup(
            "Your answers no longer call for {list}. {It} stays in the specification with any "
            "amendments until you take {it_} out.{button}").format(
            list=Markup("; ").join(Markup("<strong>{}</strong> {} ({})").format(
                x["number"], specs_check.title_case(x["title"]), x["applies"]) for x in out),
            It="It" if one else "They", it_="it" if one else "them",
            button=Markup('<form method="post" action="{url}" class="flash-action">{ids}'
                          '<button type="submit" class="btn btn-ghost btn-sm">Take {it_} out</button>'
                          "</form>").format(
                url=url_for("specs.drop_ruled_out", set_id=set_id), it_="it" if one else "them",
                ids=Markup("").join(Markup('<input type="hidden" name="section_id" value="{}">').format(x["id"])
                                    for x in out))), "notice")


@bp.post("/sets/<int:set_id>/sections/ruled-out")
@login_required
def drop_ruled_out(set_id: int):
    """The sections the answers no longer call for, taken out at the engineer's word."""
    _set_or_404(set_id)
    n = store.remove_by_master(set_id, (int(v) for v in request.form.getlist("section_id") if v.isdigit()))
    flash(f"Took {n} section{'s' if n != 1 else ''} out of this specification." if n
          else "Those sections were already out.", "success")
    return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-sections")


def _read_model(set_id: int, filename: str, data: bytes) -> bool:
    from .. import specs_model

    try:
        found = specs_model.read_model(filename, data)
    except specs.SpecError as exc:
        flash(f"{filename}: {exc}", "error")
        return False
    store.save_model(set_id, found)
    changed = store.apply_model(set_id, found)
    flagged = [m for m in found.get("concrete", []) if m.get("state") == "unrealistic"]
    flash(f"Read {filename}: " + (("ticked " + "; ".join(changed) + ".") if changed else
                                  "nothing new to tick.")
          + (f" {len(flagged)} concrete grade{'s do' if len(flagged) != 1 else ' does'} not look "
             "realistic: see the model's grades below." if flagged else ""),
          "error" if flagged else "success")
    return True


# --- one project's specification ------------------------------------------------

@bp.get("/sets/<int:set_id>")
@login_required
def spec_set(set_id: int):
    row = _set_or_404(set_id)
    sections = store.set_sections(set_id)
    have = {s["section_id"] for s in sections if s["section_id"]}
    missing = []
    values = store.values_for(row)
    for s in sections:
        for name in specs.unfilled(specs.loads(s["body"]), values):
            if name not in missing:
                missing.append(name)
    chosen = store.chosen_for(row)
    asked = specs_questions.asked(sections, chosen, row, _element_slugs(chosen)) if sections else []
    report = store.check_set(set_id) if sections else None
    waiting = store.open_items(set_id, report) if report else None
    everything = store.options()
    tiles = _tiles(everything, chosen)
    library = store.library()
    model = store.model_for(row)
    return render_template(
        "specs/set.html", spec=row, sections=sections, tiles=tiles,
        blanks_n=len(store.blanks(set_id)) if sections else 0,
        details_total=len(asked), details_open=sum(not q["answered"] for q in asked),
        location=specs_questions.answers_of(row).get("proj_location", ""),
        place=store.place_of(row), countries=specs_places.country_names(),
        uncover=store.uncovered_for(row, chosen), opts={o["key"]: o for o in everything},
        groups=_grouped([o for o in everything if o["key"] not in TILE_KEYS]),
        waiting=waiting,
        chosen=chosen, picked={k: set(v.split("|")) for k, v in chosen.items()},
        variables=store.variables(), values=values, families=store.families(),
        family=store.family_name(row["family"]),
        available=[s for s in library if s["id"] not in have and s["family"] == row["family"]],
        elsewhere=[s for s in library if s["id"] not in have and s["family"] != row["family"]],
        declined=store.declined(row), model=model,
        from_model={(e["key"], specs._norm(e["value"])) for e in (model or {}).get("elements", [])},
        icons=specs_seed.ELEMENT_ICONS, group_icons=GROUP_ICONS,
        labels={o["key"]: o["label"] for o in everything},
        missing=missing, is_admin=_is_admin(), report=report, seen=review.project_mark(row),
        team=review.team(set_id), may_edit=review.may(row, g.user, "edit"),
        open_comments=review.open_comments(set_id), last_issue=review.last_issue(set_id),
        owner=review.owner_name(row), packages=_packages_summary(row))


def _packages_summary(row) -> dict:
    """The other packages of the project, and how many differences from what
    they issued this package has not decided."""
    from .. import specs_packages as packages

    found = packages.discrepancies(row) if packages.project_key(row["code"]) else None
    return {"peers": found["peers"] if found else [], "open": found["open"] if found else 0,
            "key": packages.project_key(row["code"])}


TILE_KEYS = {key for key, _g, _how, _icon in specs_seed.ELEMENTS}
GROUP_ICONS = {"Basis": "basis", "Sustainability and compliance": "sustainability",
               "Scope": "scope", "Environment": "environment", "Concrete": "concrete",
               "Reinforcement": "reinforcement", "Steel": "steel",
               "Marine furniture": "marine_furniture", "Protection": "protection",
               "Bridges": "bridges"}


def _tiles(options: list[dict], chosen: dict | None = None) -> list[dict]:
    """The element questions as tiles, under their headings: one tile a
    question, or one an answer for a question that takes several."""
    known = {o["key"]: o for o in options}
    groups = [{"key": k, "title": t, "tiles": []} for k, t in specs_seed.ELEMENT_GROUPS]
    by_key = {grp["key"]: grp for grp in groups}
    for key, grp, how, drawing in specs_seed.ELEMENTS:
        o = known.get(key)
        if o is None or not o["choice_list"]:
            continue
        if how == "many" and o["kind"] == "many":
            for c in o["choice_list"]:
                if specs._norm(c) in ("none", ""):
                    continue
                by_key[grp]["tiles"].append({"how": "many", "option": o, "value": c,
                                             "label": specs_seed.ELEMENT_LABELS.get((key, c), c),
                                             "icon": specs_seed.ELEMENT_ICONS.get((key, c), drawing)})
        elif how == "toggle" and len(o["choice_list"]) >= 2:
            on = o["choice_list"][1]
            by_key[grp]["tiles"].append({"how": "toggle", "option": o, "value": on,
                                         "off": o["choice_list"][0],
                                         "label": specs_seed.ELEMENT_LABELS.get((key, on), o["label"]),
                                         "icon": drawing})
        else:
            by_key[grp]["tiles"].append({"how": "pick", "option": o, "value": "", "label": o["label"],
                                         "icon": drawing})
    if "elements" in known and "elements" in by_key:
        _element_tiles(by_key["elements"], known["elements"], chosen or {})
    return [grp for grp in groups if grp["tiles"]]


def _element_tiles(grp: dict, o: dict, chosen: dict) -> None:
    """The structural elements: first the ones the kinds of work the project
    builds usually have, with any it has ticked and the ones its engineer
    added by name; the rest marked to go under a fold."""
    builds = {specs._norm(v) for v in (chosen.get("structures") or "").split("|")} - {""}
    usual = {specs._norm(label): {specs._norm(f) for f in fors.split("|")}
             for _slug, label, fors in specs_seed.ELEMENT_KINDS}
    have = [v for v in (chosen.get(o["key"]) or "").split("|") if v.strip()]
    ticked = {specs._norm(v) for v in have}
    for t in grp["tiles"]:
        n = specs._norm(t["value"])
        t["more"] = n not in ticked and n in usual and not usual[n] & builds
    offered = {specs._norm(c) for c in o["choice_list"]}
    for v in have:
        if specs._norm(v) not in offered and v.strip().lower() != "none":
            grp["tiles"].append({"how": "many", "option": o, "value": v, "label": v,
                                 "icon": "element", "own": True, "more": False})
    grp["tiles"].sort(key=lambda t: t["more"])


def _grouped(options: list[dict]) -> list[tuple[str, list[dict]]]:
    """The questions under their headings, in the order they were set out."""
    groups: dict[str, list[dict]] = {}
    for o in options:
        groups.setdefault(o.get("grp") or "Other", []).append(o)
    return list(groups.items())


@bp.post("/sets/<int:set_id>")
@login_required
def save_set(set_id: int):
    row = _set_or_404(set_id)
    seen = request.form.get("seen", "")
    if seen and seen != review.project_mark(row):
        # Everything on this page is sent at once: saving a page opened before
        # somebody else's change would put their answers back as they were.
        last = review.last_change(set_id)
        flash(f"{(last or {}).get('who') or 'Somebody'} changed this project "
              f"{review.minutes_ago((last or {}).get('at') or row['updated_at'])} after you opened this page, "
              "so nothing was saved over it. The page now shows the project as it stands: make your "
              "changes again and save.", "error")
        step = request.form.get("next")
        return redirect(url_for("specs.spec_set", set_id=set_id)
                        + (f"#step-{step}" if step in ("elements", "questions", "sections") else ""))
    chosen = {DECIDED: "1"}            # saving the project's choices is deciding them
    toggles = {key for key, _g, how, _i in specs_seed.ELEMENTS if how == "toggle"}
    for o in store.options():
        key = o["key"]
        if key in toggles and len(o["choice_list"]) >= 2 and key in request.form.getlist("tile_shown"):
            # A ticked tile is the question's second answer; an unticked one its first.
            chosen[key] = o["choice_list"][1] if request.form.get(f"tile_{key}") else o["choice_list"][0]
        elif o["kind"] == "many":
            ticked = [v for v in request.form.getlist(f"opt_{key}") if v]
            if not ticked and key in request.form.getlist("tile_shown"):
                ticked = [c for c in o["choice_list"] if specs._norm(c) == "none"][:1]
            chosen[key] = "|".join(ticked)
            if key == "elements":
                chosen[key] = _with_element(o, chosen[key], request.form.get("element_new", ""))
        else:
            chosen[key] = request.form.get(f"opt_{key}", "")
    values = {v["key"]: request.form.get(f"var_{v['key']}", "") for v in store.variables()}
    before = store.ruled_out(set_id)
    try:
        store.update_set(set_id, request.form, chosen, values)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        if "city" in request.form or "country" in request.form:
            store.set_place(set_id, request.form.get("city", ""), request.form.get("country", ""))
        elif "proj_location" in request.form:
            location = " ".join(request.form["proj_location"].split())
            specs_questions.save_answers(set_id, {"proj_location": location or None}, {})
        flash("Saved.", "success")
        _added(set_id, before)
    step = request.form.get("next")
    if step in ("elements", "questions", "sections"):
        return redirect(url_for("specs.spec_set", set_id=set_id) + f"#step-{step}")
    return redirect(url_for("specs.spec_set", set_id=set_id))


def _with_element(o: dict, have: str, name: str) -> str:
    """A project's elements with one more its engineer typed: a listed one
    by its label, whatever the case it was typed in; another as typed."""
    name = " ".join(name.replace("|", " ").split())
    if not name:
        return have
    listed = {specs_seed.element_slug(c): c for c in o["choice_list"]}
    name = listed.get(specs_seed.element_slug(name), name)
    now = [v for v in have.split("|") if v]
    if specs._norm(name) not in {specs._norm(v) for v in now}:
        now.append(name)
    return "|".join(now)


@bp.post("/sets/<int:set_id>/model")
@login_required
def upload_model(set_id: int):
    """The elements and concrete grades read from an export of the Revit model."""
    _set_or_404(set_id)
    if request.form.get("action") == "forget":
        store.save_model(set_id, None)
        flash("The model is forgotten. What it ticked stays ticked.", "success")
        return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-elements")
    models = _uploads("model", MOST_MODEL)
    if not models:
        flash("Choose the model's IFC export or schedule first.", "error")
    else:
        before = store.ruled_out(set_id)
        if _read_model(set_id, *models[0]):
            _added(set_id, before)
    return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-elements")


@bp.post("/sets/<int:set_id>/delete")
@login_required
def delete_set(set_id: int):
    row = _set_or_404(set_id)
    if not (_is_admin() or row["created_by"] == g.user["id"]):
        flash("Only whoever started this specification, or an administrator, can delete it.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    store.delete_set(set_id)
    flash(f"Deleted the specification for {row['name']}.", "success")
    return redirect(url_for("specs.index"))


@bp.post("/sets/<int:set_id>/sections")
@login_required
def add_sections(set_id: int):
    _set_or_404(set_id)
    picked = [int(v) for v in request.form.getlist("section_id") if v.isdigit()]
    before = store.ruled_out(set_id)
    added = store.add_sections(set_id, picked)
    # A section added by hand is the answer that calls for it, as if chosen.
    said = [line for section_id in picked for line in store.answer_for(set_id, section_id)]
    flash(f"Added {added} section{'s' if added != 1 else ''} from the library."
          + (f" The answers now say so: {'; '.join(said)}." if said else "")
          if added else "Tick the sections to add first.", "success" if added else "error")
    if said:
        _added(set_id, before)
    return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-sections")


@bp.post("/sets/<int:set_id>/sections/remove")
@login_required
def remove_sections(set_id: int):
    """Ticked sections taken out of the project, for one added by mistake."""
    _set_or_404(set_id)
    rows = {r["id"]: r for r in store.set_sections(set_id)}
    picked = [rows[int(v)] for v in request.form.getlist("row_id") if v.isdigit() and int(v) in rows]
    if not picked:
        flash("Tick the sections to take out first.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-sections")
    before = store.ruled_out(set_id)
    undone = [line for r in picked for line in store.remove_set_section(set_id, r["id"])]
    flash(f"Took {len(picked)} section{'s' if len(picked) != 1 else ''} out: "
          + ", ".join(r["number"] for r in picked) + "."
          + (f" The answers adding {'it' if len(picked) == 1 else 'them'} set are back as they "
             f"were: {'; '.join(undone)}." if undone else "")
          + " Add back any time from the library list.", "success")
    if undone:
        _added(set_id, before)
    return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-sections")


@bp.post("/sets/<int:set_id>/sections/new")
@login_required
def new_own_section(set_id: int):
    _set_or_404(set_id)
    try:
        row_id = store.new_own_section(set_id, request.form.get("number", ""),
                                       request.form.get("title", ""))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    return redirect(url_for("specs.edit_set_section", set_id=set_id, row_id=row_id))


@bp.post("/sets/<int:set_id>/upload")
@login_required
def upload_to_set(set_id: int):
    _set_or_404(set_id)
    done = []
    for filename, data in _uploads("files"):
        try:
            _row_id, how = store.import_to_set(set_id, filename, data)
        except specs.SpecError as exc:
            flash(f"{filename}: {exc}", "error")
            continue
        done.append(f"{filename} ({how})")
    if done:
        flash("Read " + ", ".join(done) + ". Anything it changed from the master shows as "
              "an amendment.", "success")
    return redirect(url_for("specs.spec_set", set_id=set_id))


@bp.get("/sets/<int:set_id>/export")
@login_required
def export_set(set_id: int):
    row = _set_or_404(set_id)
    sections = store.set_sections(set_id)
    if not sections:
        flash("There are no sections in this specification to issue yet.", "error")
        return redirect(url_for("specs.spec_set", set_id=set_id))
    # Clean Word (the default), Word with tracked changes, or one PDF; the
    # hold and the reference check stop every one of them alike.
    fmt = specs_export.fmt_of(request.args.get("fmt"))
    keep_fmt = fmt if fmt != "docx" else None
    if request.args.get("draft"):
        # A working copy, as the text stands: nothing holds it, nothing records
        # it, and every page says it was not issued.
        draft = dict(row, revision=f"{row['revision']} WORKING COPY, NOT ISSUED")
        data, name, mime = _bundle(draft, sections, fmt)
        stem, dot, ext = name.rpartition(".")
        stem = stem.replace(f" REV {draft['revision']}", f" REV {row['revision']}")
        name = f"{stem} - working copy (not issued).{ext}"
        return Response(data, mimetype=mime,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    report = store.check_set(set_id)
    if row["hold_issue"]:
        waiting = store.open_items(set_id, report)
        if waiting["total"]:
            flash(f"Not issued yet: {waiting['total']} item{'s' if waiting['total'] != 1 else ''} "
                  "on the check still to keep, amend or remove. This project is held until each one "
                  "is settled (the hold is a tick box on the project page).", "error")
            return redirect(url_for("specs.check_set", set_id=set_id, issuing=1, fmt=keep_fmt))
    missing = _not_issued(report)
    if missing and not row["hold_issue"] and not request.args.get("anyway"):
        flash(f"Not issued yet: {len(missing)} reference{'s' if len(missing) != 1 else ''} point at "
              "sections or paragraphs this specification does not issue. Add the sections, or "
              "correct the references, then issue — or issue anyway from the top of this page.",
              "error")
        return redirect(url_for("specs.check_set", set_id=set_id, issuing=1, fmt=keep_fmt))
    data, name, mime = _bundle(row, sections, fmt)
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _bundle(row: dict, sections: list[dict], fmt: str, since: dict | None = None
            ) -> tuple[bytes, str, str]:
    """The project's sections as issued: clean Word (a .zip of .docx), Word
    with tracked changes against the master, one PDF, or (``since``: an issue
    on the register) Word with every change since that issue marked.
    Returns the file, its name and its type."""
    chosen, values = store.chosen_for(row), store.values_for(row)
    template = store.template_bytes(row["family"])
    reader = store.reader(store.set_whole(row["id"]), chosen)
    name = "".join(c if c.isalnum() or c in "-_ " else "-" for c in (row["code"] or row["name"]))
    name = f'{name.strip() or "specification"} - specification REV {row["revision"]}'
    if fmt == "pdf":
        data = specs_export.write_pdf(
            [(s, specs.loads(s["body"]), reader.issued(s["number"])) for s in sections],
            row, chosen, values, template, title=row["name"])
        return data, f"{name}.pdf", "application/pdf"
    before = {s["number"]: s for s in since["snapshot"].get("sections", [])} if since else {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for s in sections:
            if fmt == "tracked" or since:
                base = (review.base_nodes(before.get(s["number"])) if since else store.base_of(s))
                data, _ = specs_export.write_tracked_docx(
                    s, specs.loads(s["body"]), base, row, chosen, values, template,
                    resolve=reader.issued(s["number"]),
                    author=f"Changes since Rev {since['revision']}" if since else (s.get("updated_by") or ""))
                bundle.writestr(specs_export.tracked_name(row["file_pattern"], s), data)
                continue
            data = specs.write_docx(s, specs.loads(s["body"]), row, chosen, values, template,
                                    resolve=reader.issued(s["number"]))
            bundle.writestr(specs.file_name(row["file_pattern"], s), data)
    if since:
        name += f" - changes since REV {since['revision']}"
    elif fmt == "tracked":
        name += " - tracked changes"
    return buffer.getvalue(), f"{name}.zip", "application/zip"


def _not_issued(report: dict) -> list[dict]:
    """References that would go out pointing at nothing this issue contains."""
    return [i for i in report["references"] if ("not in this specification" in i["message"]
            or i["severity"] == "error") and not i.get("settled")]


@bp.post("/sets/<int:set_id>/settle")
@login_required
def settle(set_id: int):
    """A check item kept as it stands, or opened again."""
    _set_or_404(set_id)
    keys = request.form.getlist("key")
    state = request.form.get("state", "")
    try:
        for key in keys:
            store.settle(set_id, key, state,
                         request.form.get("message", "") if len(keys) == 1 else "")
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        if keys and state:
            flash("Kept." if len(keys) == 1 else f"Kept all {len(keys)}.", "success")
        elif keys:
            flash("Opened again." if len(keys) == 1 else f"{len(keys)} items opened again.", "success")
    return redirect(_back_to_check(set_id) + (f"#item-{keys[0]}" if len(keys) == 1 else
                                              f"#group-{request.form.get('group', '')}"))


def _back_to_check(set_id: int, shown: str | None = None) -> str:
    """The check again; ``shown`` is an item just settled, shown open under its group."""
    return url_for("specs.check_set", set_id=set_id, issuing=request.form.get("issuing") or None,
                   fmt=request.form.get("fmt") or None, shown=shown)


@bp.post("/sets/<int:set_id>/check/amend")
@login_required
def amend_item(set_id: int):
    """A check item's paragraphs given the text the engineer settled on."""
    _set_or_404(set_id)
    key = request.form.get("key", "")
    edits = []
    for row_id, node_id, new in zip(request.form.getlist("row_id"), request.form.getlist("node_id"),
                                    request.form.getlist("text")):
        if row_id.isdigit():
            edits.append((int(row_id), node_id, new))
    try:
        detail = store.amend_item(set_id, key, edits)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(_back_to_check(set_id) + f"#item-{key}")
    flash(f"Amended: {store.labels(detail['places'])}.", "success")
    return redirect(_back_to_check(set_id, detail["key"]) + f"#item-{detail['key']}")


@bp.post("/sets/<int:set_id>/check/conflict")
@login_required
def settle_conflict(set_id: int):
    """A clause that says otherwise than an answer: the answer put in the clause,
    the answer changed to match, or the clause kept with a reason."""
    _set_or_404(set_id)
    key, how = request.form.get("key", ""), request.form.get("how", "")
    pick = int(request.form.get("pick") or 0) if (request.form.get("pick") or "0").isdigit() else 0
    try:
        if how == "use":
            detail = store.conflict_use_answer(set_id, key, pick)
            flash(f"The answer is back in {store.labels(detail['places'])}: the clause follows it from now on.",
                  "success")
            key = detail["key"]
        elif how == "change":
            detail = store.conflict_change_answer(set_id, key, pick)
            a = detail["answer_changed"]
            flash(f"“{a['label']}” is now {a['to']} (it was {a['from']}), in every clause that uses it.",
                  "success")
        elif how == "keep":
            store.conflict_keep(set_id, key, request.form.get("reason", ""))
            flash("Kept as written, with your reason.", "success")
        else:
            abort(400)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(_back_to_check(set_id) + f"#item-{key}")
    return redirect(_back_to_check(set_id, key) + f"#item-{key}")


@bp.post("/sets/<int:set_id>/check/remove")
@login_required
def remove_item(set_id: int):
    """The sentence a check item is about taken out, in every place it is."""
    _set_or_404(set_id)
    keys = request.form.getlist("key")
    try:
        done = store.remove_items(set_id, keys)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(_back_to_check(set_id) + (f"#item-{keys[0]}" if keys else ""))
    places = [p for one in done for p in one["detail"]["places"]]
    whole = [p for p in places if p["whole"]]
    if not places:
        flash("Nothing was removed: the words were not found as they stand.", "error")
    elif len(done) == 1 and len(places) == 1 and whole:
        flash(f"Removed paragraph {store.label(places[0])}: it was its only sentence"
              + (f", and the {whole[0]['under']} paragraph{'s' if whole[0]['under'] != 1 else ''} "
                 "under it went with it." if whole[0]["under"] else "."), "success")
    elif len(whole) == len(places):
        flash(f"Removed paragraphs {store.labels(places)}: the sentence was all each one said.",
              "success")
    else:
        flash(f"Removed the sentence from {store.labels(places)}."
              + (f" In {store.labels(whole)} it was the only sentence, so the paragraph went."
                 if whole else ""), "success")
    if len(done) == 1:
        return redirect(_back_to_check(set_id, done[0]["key"]) + f"#item-{done[0]['key']}")
    group = done[0]["group"] if done else request.form.get("group", "")
    return redirect(_back_to_check(set_id) + f"#group-{group}")


def _element_slugs(chosen: dict) -> list[str]:
    """The project's elements, as the text names them."""
    slug = getattr(specs_seed, "element_slug", None) or (
        lambda label: re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"))
    return [slug(e) for e in (chosen.get("elements") or "").split("|") if e.strip()]


def _asked(set_id: int, row, sections=None) -> list[dict]:
    chosen = store.chosen_for(row)
    return specs_questions.asked(store.set_sections(set_id) if sections is None else sections,
                                 chosen, row, _element_slugs(chosen))


@bp.route("/sets/<int:set_id>/details", methods=["GET", "POST"])
@login_required
def details(set_id: int):
    """The master's questions for this project, one group at a time: each
    answer is written into every clause it belongs to."""
    row = _set_or_404(set_id)
    # As a story (the default: chapters in the order the project is built) or
    # by the library's groups.
    by = "group" if request.values.get("by") == "group" else "story"
    asked = _asked(set_id, row)
    groups = specs_questions.grouped(asked) if by == "group" else specs_questions.story(asked)
    slugs = [g["slug"] for g in groups]
    asked_for = request.values.get("group", "")
    if asked_for not in slugs:
        # A group named while the questions are told as a story: its chapter.
        asked_for = next((g["slug"] for g in groups if asked_for in g.get("group_slugs", ())), asked_for)
    here = slugs.index(asked_for) if asked_for in slugs else next(
        (i for i, g in enumerate(groups) if g["open"]), 0)
    if request.method == "POST" and groups:
        given, split = specs_questions.read_form(request.form, groups[here]["questions"])
        held = _unaccepted(groups[here]["questions"], given)
        switches = {q["key"] for q in groups[here]["questions"] if q.get("switch")}
        kept = _answered_meanwhile(row, given, switches)
        before = store.ruled_out(set_id)
        specs_questions.save_switches(set_id, {k: v for k, v in given.items() if k in switches})
        specs_questions.save_answers(set_id, {k: v for k, v in given.items() if k not in switches},
                                     split)
        answered = sum(1 for k, v in given.items() if "@" not in k and v is not None)
        flash(f"Saved {answered} answer{'s' if answered != 1 else ''} in "
              f"{groups[here]['name']}.", "success")
        if held:
            flash(f"{held} suggested answer{'s were' if held != 1 else ' was'} not written in: tick "
                  "that you have reviewed the suggestions to accept them, or change each one. The "
                  "engineer decides every answer; THEMIS only suggests.", "error")
            if not kept:
                return redirect(url_for("specs.details", set_id=set_id, group=slugs[here], **_by(by)))
        if kept:
            flash("Somebody else answered " + "; ".join(kept) + " after you opened this page, so "
                  "theirs was kept; change it again if yours should stand.", "error")
            return redirect(url_for("specs.details", set_id=set_id, group=slugs[here], **_by(by)))
        if switches:
            _added(set_id, before)
        if request.form.get("go") == "back" and here:
            return redirect(url_for("specs.details", set_id=set_id, group=slugs[here - 1], **_by(by)))
        if here + 1 < len(groups) and request.form.get("go") != "stay":
            return redirect(url_for("specs.details", set_id=set_id, group=slugs[here + 1], **_by(by)))
        return redirect(url_for("specs.details", set_id=set_id, group=slugs[here], **_by(by)))
    labels = dict(specs_questions.KIND_LABELS)
    labels.update({e[0]: e[1] for e in getattr(specs_seed, "ELEMENT_KINDS", [])})
    return render_template(
        "specs/details.html", spec=row, groups=groups, group=groups[here] if groups else None, by=by,
        here=here, total=sum(len(g["questions"]) for g in groups),
        open_n=sum(g["open"] for g in groups), need_n=sum(g["need"] for g in groups), element_labels=labels,
        FREE=specs_questions.FREE, NONE=specs_questions.NONE, SAME=specs_questions.SAME,
        picked=specs_questions.picked, shown=specs_questions.shown, KEEP=specs.KEEP,
        explain_key=request.args.get("explain", ""),
        was=json.dumps(_group_answers(row, groups[here]) if groups else {}, ensure_ascii=False))


def _decide_page(row, data: dict, confirm: dict | None = None) -> dict:
    """What the brief's panel shows: the project's choices (or the ones just
    sent, while their sections wait to be confirmed)."""
    from .. import specs_inputs

    chosen = confirm["chosen"] if confirm else _brief_chosen(row)
    stored = json.loads(row["options"] or "{}")
    st = next(s for s in data["stations"] if s["id"] == "decide")
    options = store.options()
    return {"spec": row, "station": st, "level": st["level"], "may_edit": review.may(row, g.user, "edit"),
            "groups": _grouped(options), "chosen": chosen, "confirm": confirm,
            "picked": {k: set(v.split("|")) for k, v in chosen.items()},
            "when": {k: specs_inputs.brief_rule(k) for k in specs_inputs.BRIEF_WHEN},
            "applies": {o["key"]: specs_inputs.brief_applies(o["key"], chosen) for o in options},
            "asked_keys": [o["key"] for o in options if specs_inputs.brief_applies(o["key"], chosen)],
            "icons": specs_seed.ELEMENT_ICONS, "group_icons": GROUP_ICONS,
            "key_icons": {key: drawing for key, _g, _how, drawing in specs_seed.ELEMENTS},
            "decided": bool(stored.get(specs_inputs.DECIDED)), "gates": specs_inputs.BRIEF_GATES}


def _brief_chosen(row) -> dict:
    """The project's choices as the brief shows them. A brief not yet decided
    asks what the project builds and what it uses with nothing assumed: the
    answers others hang on (a steel frame, marine structures, precast...)
    start unpicked, and the site is a bare plot until they are picked."""
    from .. import specs_inputs

    chosen = store.chosen_for(row, scope=False)
    stored = json.loads(row["options"] or "{}")
    if stored.get(specs_inputs.DECIDED):
        return chosen
    return {k: v for k, v in chosen.items() if k in stored or k not in specs_inputs.BRIEF_GATES}


def _labels() -> dict:
    labels = dict(specs_questions.KIND_LABELS)
    labels.update({e[0]: e[1] for e in getattr(specs_seed, "ELEMENT_KINDS", [])})
    return labels


def _scene(set_id: int, row, sections, asked=None, words: bool = True) -> dict:
    """The picture of the works for a project: its decisions first, then its
    questions station by station, as ``specs_inputs.scene`` gives them.
    Without ``words`` the specification's sentences under each answer are
    left out (the story's cards do not show them, and they are the slow part)."""
    from .. import specs_inputs

    stored = json.loads(row["options"] or "{}")
    return specs_inputs.scene(
        asked if asked is not None else _asked(set_id, row, sections),
        review.issued_words(row, sections, marked=True) if words else [], _labels(),
        lambda row_id, node_id: url_for("specs.set_section", set_id=set_id, row_id=row_id) + f"#p-{node_id}",
        chosen=_brief_chosen(row), decided=bool(stored.get(specs_inputs.DECIDED)), options=store.options())


def _decide(set_id: int, row) -> tuple[list[tuple[str, str]], dict | None]:
    """The project's decisions as the brief's form sent them, each kept with
    the project's choices; the sections they call for put in. What to say,
    and, when they call for sections and the engineer has not yet said which
    to put in, those sections to confirm (nothing is saved until then)."""
    from .. import specs_inputs

    shown = set(request.form.getlist("shown_opt"))
    given = {}
    for o in store.options():
        key = o["key"]
        if key not in shown:
            continue
        if o["kind"] == "many":
            ticked = [v for v in request.form.getlist(f"opt_{key}") if v]
            if not ticked:
                ticked = [c for c in o["choice_list"] if specs._norm(c) == "none"][:1]
            given[key] = "|".join(ticked)
        else:
            given[key] = request.form.get(f"opt_{key}", "")
    if request.form.get("partial") == "1":
        # Kept as the engineer goes through the brief, part by part: the
        # site follows, and the sections wait for the brief to be confirmed.
        specs_questions.save_switches(set_id, given)
        return [], None
    proposed = store.scoped({**store.chosen_for(row, scope=False), **given})
    coming = store.would_add(set_id, proposed)
    asking = request.headers.get("X-Requested-With") == "fetch"
    if coming["added"] and asking and request.form.get("confirm") != "1":
        return [], {"chosen": proposed, **coming}
    if request.form.get("confirm") == "1":
        # The ones the engineer left unticked stay out, now and when the
        # answers are saved again.
        keep = {int(i) for i in request.form.getlist("add_section") if i.isdigit()}
        store._decline(set_id, add=[s["id"] for s in coming["added"] if s["id"] not in keep])
    before = store.ruled_out(set_id)
    specs_questions.save_switches(set_id, {**given, specs_inputs.DECIDED: "1"})
    _added(set_id, before)
    return [("success", "Decided. The site is drawn from these, and the questions follow from them.")], None


@bp.get("/sets/<int:set_id>/inputs")
@login_required
def review_inputs(set_id: int):
    """The project's inputs at a glance before it is issued: every question on
    a picture of the works as they are built, answered there stage by stage,
    and the same as a plain summary."""
    row = _set_or_404(set_id)
    sections = store.set_sections(set_id)
    data = _scene(set_id, row, sections)
    left = review.still_open(row, sections) if sections else []
    return render_template("specs/inputs.html", spec=row, scene=data, left=left,
                           open_places=sum(len(p["open"]) for p in left))


@bp.get("/sets/<int:set_id>/story")
@login_required
def story(set_id: int):
    """The questions answered as the story of the works: level by level along
    a path through the site, from deciding the project to the finished
    structure, each level told in a few lines and its questions answered at
    its stations in the picture. The list of Details is its list view."""
    row = _set_or_404(set_id)
    data = _scene(set_id, row, store.set_sections(set_id))
    return render_template("specs/story.html", spec=row, scene=data)


@bp.route("/sets/<int:set_id>/inputs/<station>", methods=["GET", "POST"])
@login_required
def inputs_station(set_id: int, station: str):
    """One station's questions, to answer or change from the picture: the
    panel's form (GET), saved like a page of Details (POST, answered as JSON
    with the picture's new data when the page asks for it)."""
    from .. import specs_inputs

    row = _set_or_404(set_id)
    sections = store.set_sections(set_id)
    asked = _asked(set_id, row, sections)
    if station == "decide":
        chapter, questions = dict(specs_inputs.DECIDING), []
    else:
        chapter, questions = specs_inputs.station_questions(asked, station)
    if chapter is None:
        abort(404)
    # The story asks one question at a time: its card saves only that one.
    only = request.form.get("only") if request.method == "POST" else None
    if only:
        questions = [q for q in questions if q["key"] == only]
        if not questions:
            abort(404)
    wants_json = request.headers.get("X-Requested-With") == "fetch"
    # A card saved from the story wants only the picture's state back, fast:
    # the sentences of the specification are not drawn there.
    light = bool(only) and wants_json
    if request.method == "POST":
        data = _scene(set_id, row, sections, asked, words=not light)
        messages = []
        if specs_inputs.blocking(data, station):
            messages.append(("error", "This level is locked until the one before it is answered."))
        elif station == "decide":
            said, confirm = _decide(set_id, row)
            messages += said
            if confirm:
                n = len(confirm["added"])
                return {"messages": [{"kind": "info", "text": f"These choices call for {n} more section{'s' if n != 1 else ''}. "
                                                              "Nothing is saved yet: tick the ones to put in, then confirm."}],
                        "scene": data,
                        "html": render_template("specs/_decide.html", **_decide_page(row, data, confirm))}
        else:
            given, split = specs_questions.read_form(request.form, questions)
            held = _unaccepted(questions, given)
            switches = {q["key"] for q in questions if q.get("switch")}
            kept = _answered_meanwhile(row, given, switches)
            before = store.ruled_out(set_id)
            specs_questions.save_switches(set_id, {k: v for k, v in given.items() if k in switches})
            specs_questions.save_answers(set_id, {k: v for k, v in given.items() if k not in switches}, split)
            answered = sum(1 for k, v in given.items() if "@" not in k and v is not None)
            messages.append(("success", f"Saved {answered} answer{'s' if answered != 1 else ''}."))
            if held:
                messages.append(("error", f"{held} suggested answer{'s were' if held != 1 else ' was'} not "
                                          "written in: tick that you accept the suggestions, or change "
                                          "each one."))
            if kept:
                messages.append(("error", "Somebody else answered " + "; ".join(kept) + " after you opened "
                                          "this, so theirs was kept."))
            if switches:
                _added(set_id, before)
        if not wants_json:
            for kind, text in messages:
                flash(text, kind)
            back = "specs.story" if request.form.get("from") == "story" else "specs.review_inputs"
            return redirect(url_for(back, set_id=set_id) + f"#st-{station}")
        row = store.spec_set(set_id)
        # An answer changes no section; a decision may put sections in.
        same = light and not any(q.get("switch") for q in questions)
        after = _scene(set_id, row, sections if same else store.set_sections(set_id), words=not light)
        # A change that puts new questions in a level reopens it: say where.
        was = {c["slug"]: c["needed"] + c["suggested"] for c in data["chapters"]}
        for c in after["chapters"]:
            more = c["needed"] + c["suggested"] - was.get(c["slug"], 0)
            if more > 0 and c["slug"] != "deciding":
                messages.append(("info", f"Level {c['level']}, {c['name']}, has {more} new question"
                                         f"{'s' if more != 1 else ''} to answer."))
        # What the save flashed for the next page (sections put in or ruled
        # out) is said in the panel instead.
        out = [{"kind": k, "text": t} for k, t in messages]
        out += [{"kind": k, "html": str(t if isinstance(t, Markup) else escape(t))}
                for k, t in get_flashed_messages(with_categories=True)]
        reply = {"messages": out, "scene": after}
        if only:
            # What a card saved, for its next save to tell its own change from somebody else's.
            reply["was"] = json.dumps(_group_answers(row, {"questions": questions}), ensure_ascii=False)
        return reply
    data = _scene(set_id, row, sections, asked, words=not request.args.get("cards"))
    st = next((s for s in data["stations"] if s["id"] == station), None)
    if st is None:
        abort(404)
    if station == "decide":
        return render_template("specs/_decide.html", **_decide_page(row, data))
    if request.args.get("cards"):
        return render_template(
            "specs/_cards.html", spec=row, station=st, questions=questions,
            locked=specs_inputs.blocking(data, station), may_edit=review.may(row, g.user, "edit"),
            element_labels=_labels(), pictures=_pictures(questions, row["family"], store.chosen_for(row)),
            split_location=specs_places.split_location, join_location=specs_places.join_location,
            countries=specs_places.country_names(),
            cities=sorted({n.title() for n, *_rest in specs_places.CITIES}),
            was={q["key"]: json.dumps(_group_answers(row, {"questions": [q]}), ensure_ascii=False) for q in questions},
            FREE=specs_questions.FREE, NONE=specs_questions.NONE, SAME=specs_questions.SAME,
            picked=specs_questions.picked, shown=specs_questions.shown, KEEP=specs.KEEP)
    return render_template(
        "specs/_station.html", spec=row, station=st, chapter=chapter, questions=questions, level=st["level"],
        locked=specs_inputs.blocking(data, station), may_edit=review.may(row, g.user, "edit"),
        mix=data["mix"] if station == "mixer" else None, element_labels=_labels(),
        was=json.dumps(_group_answers(row, {"questions": questions}), ensure_ascii=False),
        FREE=specs_questions.FREE, NONE=specs_questions.NONE, SAME=specs_questions.SAME,
        picked=specs_questions.picked, shown=specs_questions.shown, KEEP=specs.KEEP)


def _pictures(questions: list[dict], family: str, chosen: dict | None = None) -> dict[str, dict]:
    """What each question's card shows above it: its drawing, or the first
    picture added to it, and what it means in a line or two (its examples
    only the ones that fit what the project builds)."""
    off_words = specs_questions.off_scope(chosen or {})
    out = {}
    for q in questions:
        found = specs_questions.explained(q["key"], family) or {}
        shots = found.get("pictures") or []
        out[q["key"]] = {"drawing": found.get("drawing") or "", "image": shots[0] if shots else None,
                         "definition": specs_questions.scope_examples(found.get("definition") or "", off_words)}
    return out


def _by(by: str) -> dict:
    return {"by": "group"} if by == "group" else {}


def _unaccepted(questions: list[dict], given: dict) -> int:
    """Suggested answers left as suggested, taken out of ``given`` unless the
    engineer ticked that they reviewed and accept them: THEMIS suggests, the
    engineer decides. One the engineer changed is their own answer and stays."""
    if request.form.get("suggest_shown") != "1" or request.form.get("accept_suggested") == "1":
        return 0
    held = 0
    for q in questions:
        if q.get("answered") or q.get("suggested") is None or q["key"] not in given:
            continue
        if " ".join(str(given[q["key"]]).split()) == " ".join(str(q["suggested"]).split()):
            given.pop(q["key"])
            held += 1
    return held


def _group_answers(row: dict, group: dict) -> dict:
    """The answers a group's page shows as it is opened, to tell a later save
    which of them somebody else has changed since."""
    keys = {q["key"] for q in group["questions"] if not q.get("switch")}
    return {k: v for k, v in specs_questions.answers_of(row).items() if k.partition("@")[0] in keys} \
        | {k: None for k in keys if k not in specs_questions.answers_of(row)}


def _answered_meanwhile(row: dict, given: dict, switches: set) -> list[str]:
    """Answers somebody else changed after this page was opened, taken out of
    ``given`` so this save does not put back what the page showed; in words."""
    try:
        was = json.loads(request.form.get("was") or "null")
    except ValueError:
        was = None
    if not isinstance(was, dict):
        return []
    now = specs_questions.answers_of(store.spec_set(row["id"]))
    labels = {k: d.get("label") or k for k, d in specs_questions.definitions().items()}
    kept = []
    for key in list(given):
        if key in switches or key.partition("@")[0] not in {k.partition("@")[0] for k in was}:
            continue
        if was.get(key) != now.get(key) and given[key] != now.get(key):
            kept.append(f"{labels.get(key.partition('@')[0], key)} ({now.get(key) or 'cleared'})")
            given.pop(key)
    return kept


@bp.get("/sets/<int:set_id>/explain/<key>")
@login_required
def explain(set_id: int, key: str):
    """The side panel beside a question: what it means, a drawing of it, and
    what the project's codes say about it, with their screenshots."""
    row = _set_or_404(set_id)
    found = specs_questions.explained(key, row["family"])
    if found is None:
        abort(404)
    asked = next((q for q in _asked(set_id, row) if q["key"] == key), None)
    off_words = specs_questions.off_scope(store.chosen_for(row))
    return render_template(
        "specs/_explain.html", spec=row, q=found, asked=asked, admin=_is_admin(),
        means=specs_questions.scope_examples(found["definition"] or "", off_words),
        hint=specs_questions.scope_examples(found.get("help") or "", off_words),
        refs_text=specs_questions.refs_as_lines(specs_questions.refs_of(found)),
        drawings=specs_questions.drawings(), group=request.args.get("group", ""))


def _back_to_panel(key: str):
    set_id = request.form.get("set_id", type=int)
    if set_id:
        return redirect(url_for("specs.details", set_id=set_id, group=request.form.get("group") or None,
                                explain=key))
    return redirect(url_for("specs.index"))


@bp.post("/questions/<key>/explain")
@login_required
def save_explanation(key: str):
    if _admin_only() and key in specs_questions.definitions():
        specs_questions.save_explanation(
            key, request.form.get("definition", ""), request.form.get("picture", ""),
            specs_questions.refs_from_lines(request.form.get("refs", "")),
            request.form.get("kind", "") if request.form.get("only_kind") else "")
        flash("Saved the explanation. Every project sees it.", "success")
    return _back_to_panel(key)


@bp.post("/questions/<key>/images")
@login_required
def add_question_images(key: str):
    if _admin_only() and key in specs_questions.definitions():
        code, clause = request.form.get("code", ""), request.form.get("clause", "")
        added = bad = 0
        for f in request.files.getlist("image"):
            data = f.read()
            if not data:
                continue
            if specs_questions.add_image(key, data, code, clause, request.form.get("caption", ""),
                                         store._who()):
                added += 1
            else:
                bad += 1
        if added:
            flash(f"Added {added} picture{'s' if added != 1 else ''}"
                  + (f" to {code} {clause}".rstrip() if code else "") + ".", "success")
        if bad:
            flash(f"{bad} file{'s were' if bad != 1 else ' was'} not added: only PNG, JPEG, GIF "
                  f"or WebP pictures up to {specs_questions.IMAGE_LIMIT // (1024 * 1024)} MB.", "error")
        if not added and not bad:
            flash("Choose or paste a picture first.", "error")
    return _back_to_panel(key)


@bp.post("/questions/<key>/images/<int:image_id>/delete")
@login_required
def delete_question_image(key: str, image_id: int):
    found = specs_questions.image(image_id)
    if _admin_only() and found and found["key"] == key:
        specs_questions.delete_image(image_id)
        flash("Took the picture out.", "success")
    return _back_to_panel(key)


@bp.get("/question-images/<int:image_id>")
@login_required
def question_image(image_id: int):
    found = specs_questions.image(image_id)
    if found is None:
        abort(404)
    response = Response(found["content"], mimetype=found["mime"])
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/sets/<int:set_id>/blanks", methods=["GET", "POST"])
@login_required
def blanks(set_id: int):
    """The [choices] and <Insert ...> places the master leaves for the project:
    each answer is written into the project's text in place of its blank."""
    row = _set_or_404(set_id)
    if request.method == "POST":
        answers = {}
        for key in request.form.getlist("key"):
            pick = request.form.get(f"pick_{key}", "")
            typed = request.form.get(f"free_{key}", "").strip()
            if pick in ("", "__free__"):
                # Words typed in the box count even if its button was not pressed.
                if not typed:
                    continue
                words = typed
            else:
                words = "" if pick == "__none__" else pick
            answers[key] = (words, bool(request.form.get(f"all_{key}")))
        filled = store.fill_blanks(set_id, answers)
        if filled:
            flash(f"Filled {filled} blank{'s' if filled != 1 else ''}. The words are now in "
                  "the project's text and show as amendments to the master.", "success")
        else:
            flash("Nothing was filled: pick an answer, or type one, for a blank first.", "error")
        return redirect(url_for("specs.blanks", set_id=set_id,
                                section=request.form.get("section", type=int)))
    found = store.blanks(set_id)
    order = [s["id"] for s in store.set_sections(set_id)]
    groups: dict[int, dict] = {}
    for b in found:
        g = groups.setdefault(b["row_id"], {"row_id": b["row_id"], "number": b["number"],
                                           "title": b["title"], "count": 0, "paragraphs": []})
        g["count"] += 1
        paras = g["paragraphs"]
        if not paras or paras[-1]["node_id"] != b["node_id"]:
            paras.append({"node_id": b["node_id"], "label": b["label"], "article": b["article"],
                          "text": b["text"], "blanks": []})
        paras[-1]["blanks"].append(dict(b, n=len(paras[-1]["blanks"]) + 1))
    for g in groups.values():
        for para in g["paragraphs"]:
            # The paragraph's words in pieces, each blank numbered where it stands.
            parts, at = [], 0
            for b in para["blanks"]:
                parts += [(para["text"][at:b["start"]], None), (b["run"], b["n"])]
                at = b["end"]
            para["parts"] = parts + [(para["text"][at:], None)]
    # One section at a time: the one asked for, else the next one still with blanks.
    asked = request.args.get("section", type=int)
    if asked not in groups:
        later = [r for r in order[order.index(asked) + 1:] if r in groups] if asked in order else []
        asked = (later or [r for r in order if r in groups] or [None])[0]
    listed = [groups[r] for r in order if r in groups]
    here = listed.index(groups[asked]) if asked else 0
    repeats: dict[str, int] = {}
    for b in found:
        repeats[b["run"]] = repeats.get(b["run"], 0) + 1
    return render_template(
        "specs/blanks.html", spec=row, groups=listed, total=len(found), repeats=repeats,
        current=groups.get(asked), after=listed[here + 1] if asked and here + 1 < len(listed) else None,
        before=listed[here - 1] if asked and here else None)


@bp.get("/sets/<int:set_id>/amendments")
@login_required
def amendments(set_id: int):
    """Everything this project says that the master does not, section by section."""
    row = _set_or_404(set_id)
    report = []
    for s in store.set_sections(set_id):
        base = store.base_of(s)
        nodes = specs.loads(s["body"])
        if base is None:
            report.append({"section": s, "own": True, "marked": [], "count": len(nodes)})
            continue
        marked = [m for m in specs.compare(base, nodes) if m["state"] != "same"]
        if marked:
            report.append({"section": s, "own": False, "marked": marked, "count": len(marked)})
    return render_template("specs/amendments.html", spec=row, report=report)


# --- one section of a project's specification -----------------------------------

@bp.get("/sets/<int:set_id>/sections/<int:row_id>")
@login_required
def set_section(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    s = _set_section_or_404(set_id, row_id)
    nodes = specs.loads(s["body"])
    base = store.base_of(s)
    chosen = store.chosen_for(row)
    words = next((w for w in review.issued_words(row) if w["row_id"] == row_id), None)
    stages = review.signoffs(set_id, {row_id: review.fingerprint(words)} if words else {}).get(row_id, {})
    threads = review.comments(set_id, row_id)
    by_node: dict[str, list[dict]] = {}
    for t in threads:
        by_node.setdefault(t["node_id"], []).append(t)
    here = {n["id"] for n in nodes}
    back = url_for("specs.set_section", set_id=set_id, row_id=row_id)
    lead = review.role_of(row, g.user) == "lead"
    return render_template(
        "specs/section.html", spec=row, section=s, rows=_rows(nodes, chosen, base),
        compared=base is not None, values=store.values_for(row), is_admin=_is_admin(),
        options=store.options(), chosen=chosen,
        reader=store.reader(store.set_whole(set_id), chosen),
        master=store.section(s["section_id"]) if s["section_id"] else None,
        cmt={"spec": row, "back": back, "threads": by_node,
             "may_close": lambda c: review.may_close(row, c)},
        general=by_node.get("", []), lost=[t for k, ts in by_node.items() if k and k not in here for t in ts],
        open_n=sum(t["state"] == "open" for t in threads), stages=stages, STAGES=review.STAGES,
        STAGE_NAMES=review.STAGE_NAMES, standing=review.standing(stages),
        may={w: review.may(row, g.user, w) for w in ("edit", "prepared", "checked", "approved")},
        take_back=lambda x: lead or x["user_id"] == g.user["id"], editing=review.editing(row_id))


@bp.route("/sets/<int:set_id>/sections/<int:row_id>/edit", methods=["GET", "POST"])
@login_required
def edit_set_section(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    s = _set_section_or_404(set_id, row_id)
    if request.method == "POST":
        try:
            nodes = _edited_nodes(s["body"])
        except specs.SpecError as exc:
            flash(str(exc), "error")
            return redirect(url_for("specs.edit_set_section", set_id=set_id, row_id=row_id))
        seen = request.form.get("seen", "")
        if seen and seen != review.section_mark(s):
            # Somebody saved this section after this editor was opened: nothing
            # is saved over them; the engineer's own version is shown again to
            # look at theirs first and then save on purpose.
            flash(Markup("{who} saved this section {when} while you were editing, so yours was not "
                         "saved over it. Your version is below: <a href=\"{url}\" target=\"_blank\">see "
                         "theirs</a>, then Save to put yours in its place.").format(
                who=s["updated_by"] or "Somebody", when=review.minutes_ago(s["updated_at"]),
                url=url_for("specs.set_section", set_id=set_id, row_id=row_id)), "error")
            mine = dict(s, body=specs.dumps(nodes),
                        title=(request.form.get("title") or s["title"]).strip().upper(),
                        doc_code=(request.form.get("doc_code") if request.form.get("doc_code") is not None
                                  else s["doc_code"]).strip())
            return _editor(mine, row["family"], library=False, spec=row, seen=review.section_mark(s))
        store.save_set_section(set_id, row_id, nodes, title=request.form.get("title"),
                               doc_code=request.form.get("doc_code"))
        review.stop_editing(row_id)
        flash("Saved. Anything that differs from the master is marked.", "success")
        if request.form.get("stay"):
            return redirect(url_for("specs.edit_set_section", set_id=set_id, row_id=row_id))
        return redirect(url_for("specs.set_section", set_id=set_id, row_id=row_id))
    others = review.start_editing(row_id)
    if others:
        flash(Markup("{names} opened this section in the editor {when}. If you both save, the second "
                     "save is stopped and shown the first, so nothing is lost; still, a word first "
                     "saves the work.").format(
            names=", ".join(o["name"] for o in others), when=review.minutes_ago(others[0]["since"])),
            "notice")
    return _editor(s, row["family"], library=False, spec=row, seen=review.section_mark(s))


@bp.post("/sets/<int:set_id>/sections/<int:row_id>/<action>")
@login_required
def set_section_action(set_id: int, row_id: int, action: str):
    _set_or_404(set_id)
    s = _set_section_or_404(set_id, row_id)
    back = url_for("specs.set_section", set_id=set_id, row_id=row_id)
    try:
        if action == "reset":
            store.reset_to_master(set_id, row_id)
            flash("Back to the master text. This project's amendments to it are gone.", "success")
        elif action == "update":
            store.bring_up_to_date(set_id, row_id)
            flash("Brought in the master's changes. This project's own amendments were kept.",
                  "success")
        elif action == "remove":
            undone = store.remove_set_section(set_id, row_id)
            flash(f"Took section {s['number']} out of this specification. It stays out when the "
                  "answers are saved again; add it back from the library list any time."
                  + (f" The answers adding it set are back as they were: {'; '.join(undone)}."
                     if undone else ""), "success")
            return redirect(url_for("specs.spec_set", set_id=set_id) + "#step-sections")
        elif action == "promote":
            if not _admin_only():
                return redirect(back)
            store.promote(set_id, row_id)
            flash(f"Section {s['number']} in the library now reads as this project has it.",
                  "success")
        else:
            abort(404)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    return redirect(back)


@bp.get("/sets/<int:set_id>/sections/<int:row_id>/docx")
@login_required
def set_section_docx(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    s = _set_section_or_404(set_id, row_id)
    chosen = store.chosen_for(row)
    reader = store.reader(store.set_whole(set_id), chosen)
    fmt = specs_export.fmt_of(request.args.get("fmt"))
    values, template = store.values_for(row), store.template_bytes(row["family"])
    if fmt == "pdf":
        data = specs_export.write_pdf([(s, specs.loads(s["body"]), reader.issued(s["number"]))],
                                      row, chosen, values, template)
        return _pdf_response(data, specs_export.pdf_name(row["file_pattern"], s))
    if fmt == "tracked":
        data, _ = specs_export.write_tracked_docx(
            s, specs.loads(s["body"]), store.base_of(s), row, chosen, values, template,
            resolve=reader.issued(s["number"]), author=s.get("updated_by") or "")
        return _docx_response(data, specs_export.tracked_name(row["file_pattern"], s))
    data = specs.write_docx(s, specs.loads(s["body"]), row, chosen, values, template,
                            resolve=reader.issued(s["number"]))
    return _docx_response(data, specs.file_name(row["file_pattern"], s))


def _pdf_response(data: bytes, name: str) -> Response:
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- the library ------------------------------------------------------------------

@bp.get("/library")
@login_required
def library():
    families = store.families()
    family = request.args.get("family") or next((f["code"] for f in families if f["sections"]),
                                                store.DEFAULT_FAMILY)
    return render_template("specs/library.html", sections=store.library(family), family=family,
                           families=families, template=store.template_row(),
                           family_templates=store.family_templates(), is_admin=_is_admin(),
                           opts={o["key"]: o for o in store.options()})


@bp.post("/library/upload")
@login_required
def upload_to_library():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    done = []
    family = store.clean_family(request.form.get("family"))
    for filename, data in _uploads("files"):
        try:
            _section_id, how = store.import_to_library(filename, data, family)
        except specs.SpecError as exc:
            flash(f"{filename}: {exc}", "error")
            continue
        done.append(f"{filename} ({how})")
    if done:
        flash("Read " + ", ".join(done) + ". Check each one reads right before a project "
              "takes it.", "success")
    return redirect(url_for("specs.library", family=family))


@bp.post("/library/new")
@login_required
def new_library_section():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    starter = [specs.node("PRT", "GENERAL"), specs.node("ART", "RELATED DOCUMENTS"),
               specs.node("PR1", "Drawings and general provisions of the Contract, including "
                                 "General and Supplementary Conditions and Division 01 "
                                 "Specification Sections, apply to this Section."),
               specs.node("ART", "SUMMARY"), specs.node("PRT", "PRODUCTS"),
               specs.node("PRT", "EXECUTION")]
    try:
        section_id = store.save_section(request.form.get("number", ""),
                                        request.form.get("title", ""), starter, note="Started",
                                        family=store.clean_family(request.form.get("family")))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.library"))
    return redirect(url_for("specs.edit_library_section", section_id=section_id))


def _library_or_404(section_id: int) -> dict:
    row = store.section(section_id)
    if row is None:
        abort(404)
    return row


@bp.get("/library/<int:section_id>")
@login_required
def library_section(section_id: int):
    s = _library_or_404(section_id)
    version = request.args.get("v", type=int)
    nodes = (store.version_body(section_id, version) if version else None) or specs.loads(s["body"])
    # The master is shown with every condition holding, so nothing is hidden
    # from the person keeping it; what each project sees is on its own page.
    rows = [dict(p, state="same", was=None) for p in _number_all(nodes)]
    return render_template(
        "specs/section.html", spec=None, section=s, rows=rows, compared=False,
        values={v["key"]: v["default_value"] for v in store.variables()}, chosen={},
        reader=store.reader(store.library_whole(s["family"]), _every_choice(), standards=False),
        options=store.options(), versions=store.versions(section_id), version=version,
        is_admin=_is_admin(), master=None)


def _every_choice() -> dict[str, str]:
    """Every answer to every question at once: the master read whole."""
    return {o["key"]: "|".join(o["choice_list"]) for o in store.options()}


def _number_all(nodes):
    """Numbered as if every condition held, for reading the master whole."""
    shown = specs.number([dict(n, when="") for n in nodes])
    for original, one in zip(nodes, shown):
        one["when"] = original.get("when", "")
    return shown


@bp.route("/library/<int:section_id>/edit", methods=["GET", "POST"])
@login_required
def edit_library_section(section_id: int):
    s = _library_or_404(section_id)
    if not _is_admin():
        flash("Only an administrator changes the master library.", "error")
        return redirect(url_for("specs.library_section", section_id=section_id))
    if request.method == "POST":
        try:
            nodes = _edited_nodes(s["body"])
            store.save_section(request.form.get("number", s["number"]),
                               request.form.get("title", s["title"]), nodes,
                               note=request.form.get("note", "").strip(), section_id=section_id)
            store.set_applies(section_id, request.form.get("applies", ""))
        except specs.SpecError as exc:
            flash(str(exc), "error")
            return redirect(url_for("specs.edit_library_section", section_id=section_id))
        flash("Saved as a new version. Projects that took the last one can bring this in.",
              "success")
        if request.form.get("stay"):
            return redirect(url_for("specs.edit_library_section", section_id=section_id))
        return redirect(url_for("specs.library_section", section_id=section_id))
    return _editor(s, s["family"], library=True)


@bp.post("/library/<int:section_id>/delete")
@login_required
def delete_library_section(section_id: int):
    s = _library_or_404(section_id)
    if not _admin_only():
        return redirect(url_for("specs.library_section", section_id=section_id))
    store.delete_section(section_id)
    flash(f"Took section {s['number']} out of the library. Projects keep their copies.", "success")
    return redirect(url_for("specs.library"))


@bp.get("/library/<int:section_id>/docx")
@login_required
def library_docx(section_id: int):
    s = _library_or_404(section_id)
    chosen = store.chosen_for(None)
    reader = store.reader(store.library_whole(s["family"]), chosen, standards=False)
    values = {v["key"]: v["default_value"] for v in store.variables()}
    if request.args.get("fmt") == "pdf":
        data = specs_export.write_pdf([(s, specs.loads(s["body"]), reader.issued(s["number"]))],
                                      {"revision": ""}, chosen, values,
                                      store.template_bytes(s["family"]), marked=False)
        return _pdf_response(data, specs_export.pdf_name("SPC-{number}", s))
    data = specs.write_docx(s, specs.loads(s["body"]), {"revision": ""}, chosen, values,
                            store.template_bytes(s["family"]), resolve=reader.issued(s["number"]),
                            marked=False)
    return _docx_response(data, specs.file_name("SPC-{number}", s))


# --- reading as a book ------------------------------------------------------------------
# The text as it goes out — only the paragraphs the project keeps, no editor's
# notes, no amendment marks — laid out on pages like the issued document, two
# to a spread. The pages themselves are cut by spec-book.js in the browser.

def _book_section(s: dict, project: dict, chosen: dict) -> dict:
    nodes = specs.loads(s["body"])
    blocks = [{"id": n["id"], "level": n["level"], "label": n["label"], "indent": n["indent"],
               "text": specs.choose(n["text"], chosen)}
              for n in specs.number(nodes, chosen)
              if n["included"] and n["level"] != specs.NOTE]
    revision = str(project.get("revision") or "").strip()
    code = (s.get("doc_code") or project.get("doc_code") or "").strip()
    return {"id": s["id"], "number": s["number"], "title": (s["title"] or "").upper(),
            "nbs": specs.is_nbs(nodes), "blocks": blocks,
            "code_line": " ".join(b for b in (code, f"REV {revision}" if revision else "") if b)}


def _book_header(project: dict) -> list[tuple[str, str]]:
    """The running header's lines, left and right, as the issued document has them."""
    left = [line.rstrip() for line in (project.get("header_left") or "").splitlines()]
    right = [line.rstrip() for line in (project.get("header_right") or "").splitlines()]
    return [(left[i] if i < len(left) else "", right[i] if i < len(right) else "")
            for i in range(max(len(left), len(right)))]


@bp.get("/sets/<int:set_id>/book")
@login_required
def set_book(set_id: int):
    row = _set_or_404(set_id)
    chosen = store.chosen_for(row)
    sections = [_book_section(s, row, chosen) for s in store.set_sections(set_id)]
    return render_template(
        "specs/book.html", spec=row, sections=sections, values=store.values_for(row),
        reader=store.reader(store.set_whole(set_id), chosen),
        header=_book_header(row) or [(row["name"], row["code"] or "")],
        start_row=request.args.get("row", type=int),
        back=url_for("specs.spec_set", set_id=set_id), back_label=row["name"])


@bp.get("/library/<int:section_id>/book")
@login_required
def library_book(section_id: int):
    s = _library_or_404(section_id)
    chosen = store.chosen_for(None)
    return render_template(
        "specs/book.html", spec=None, sections=[_book_section(s, {}, chosen)],
        values={v["key"]: v["default_value"] for v in store.variables()},
        reader=store.reader(store.library_whole(s["family"]), chosen, standards=False),
        header=[("Master library", store.family_name(s["family"]))], start_row=None,
        back=url_for("specs.library_section", section_id=section_id),
        back_label=f"{s['number']} {s['title']}")


# --- options, variables and the template ---------------------------------------------

@bp.route("/options", methods=["GET", "POST"])
@login_required
def options():
    if request.method == "POST":
        if not _admin_only():
            return redirect(url_for("specs.options"))
        form = request.form
        store.save_options({"key": k, "label": l, "choices": c, "default_value": d, "grp": gr,
                            "kind": kd}
                           for k, l, c, d, gr, kd in zip(
                               form.getlist("opt_key"), form.getlist("opt_label"),
                               form.getlist("opt_choices"), form.getlist("opt_default"),
                               form.getlist("opt_grp"), form.getlist("opt_kind")))
        store.save_variables({"key": k, "label": l, "default_value": d}
                             for k, l, d in zip(form.getlist("var_key"), form.getlist("var_label"),
                                                form.getlist("var_default")))
        flash("Saved.", "success")
        return redirect(url_for("specs.options"))
    return render_template("specs/options.html", options=store.options(),
                           variables=store.variables(), is_admin=_is_admin())


@bp.post("/template")
@login_required
def upload_template():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    files = _uploads("template")
    family = request.form.get("family", "")
    family = store.clean_family(family) if family else ""
    if files:
        filename, data = files[0]
        try:
            store.save_template(filename, data, family)
        except specs.SpecError as exc:
            flash(str(exc), "error")
        else:
            flash(f"Every {family + ' ' if family else ''}section now goes out in {filename}'s "
                  "styles, page and header.", "success")
    return redirect(url_for("specs.library", family=family or None))


@bp.post("/template/delete")
@login_required
def delete_template():
    family = request.form.get("family", "")
    if _admin_only():
        store.drop_template(store.clean_family(family) if family else "")
        flash(f"{family} sections go out in the office's template again." if family
              else "Back to the built-in template.", "success")
    return redirect(url_for("specs.library", family=family or None))


@bp.get("/template")
@login_required
def download_template():
    family = request.args.get("family", "")
    row = store.template_row(family) or store.template_row()
    data = store.template_bytes(family) or specs.TEMPLATE.read_bytes()
    return _docx_response(data, row["filename"] if row else "spec-template.docx")


@bp.post("/options/suggested")
@login_required
def add_suggested():
    if _admin_only():
        added = store.add_suggested()
        flash(f"Added {added} question{'s' if added != 1 else ''}, choices and words from the "
              "starting list." if added else "Everything on the starting list is already here.",
              "success")
    return redirect(url_for("specs.options"))


# --- standards ------------------------------------------------------------------------

@bp.route("/standards", methods=["GET", "POST"])
@login_required
def standards():
    if request.method == "POST":
        if not _admin_only():
            return redirect(url_for("specs.standards"))
        form = request.form
        store.save_standards(
            ({"topic": t, "bs": b, "us": u} for t, b, u in
             zip(form.getlist("eq_topic"), form.getlist("eq_bs"), form.getlist("eq_us"))),
            ({"old": o, "new": n, "note": t} for o, n, t in
             zip(form.getlist("wd_old"), form.getlist("wd_new"), form.getlist("wd_note"))))
        store.save_wording(
            {"find": f, "replace": r, "note": t, "cond": c, "unless_next": u} for f, r, t, c, u in
            zip(form.getlist("wo_find"), form.getlist("wo_replace"), form.getlist("wo_note"),
                form.getlist("wo_cond"), form.getlist("wo_unless")))
        flash("Saved. Every specification now reads its standards from this.", "success")
        return redirect(url_for("specs.standards"))
    return render_template("specs/standards.html", pairs=store.equivalents(),
                           gone=store.withdrawn(), words=store.wording(), is_admin=_is_admin())


# --- the checker ----------------------------------------------------------------------

CHECKS = [
    ("model", "The model's grades",
     "Concrete and steel grades read from the Revit model that do not look realistic, need a "
     "second look, or could not be read."),
    ("answers", "Against the answers",
     "Clauses you amended or wrote yourself that give a different value from the answer to the "
     "question they belong to (40 mm typed where cover is answered as 50 mm). Use the answer, "
     "change the answer, or keep your words with a reason."),
    ("references", "Cross-references",
     "References to sections, articles and paragraphs that are not there, or not issued."),
    ("outdated", "Outdated standards", "Standards cited that have been withdrawn or superseded."),
    ("standards", "Standards off the project's basis",
     "Citations the project's basis cannot convert, because no equivalent is recorded."),
    ("discrepancies", "Discrepancies",
     "The same property given different values, sections cited under the wrong title, "
     "a standard cited in two editions."),
    ("repeated", "Repeated", "Values written out many times, and paragraphs said more than once. "
                             "Advice on keeping the text tidy: these do not hold the issue."),
    ("setup", "Set-up", "Conditions naming questions or answers that do not exist, and words "
                        "with no value."),
]


@bp.get("/sets/<int:set_id>/check")
@login_required
def check_set(set_id: int):
    from .. import specs_inputs

    row = _set_or_404(set_id)
    report = store.check_set(set_id)
    store.check_actions(set_id, report)
    language = _language(store.language_set(set_id))
    # The same picture of the works as the inputs at a glance, each open
    # finding pinned at the station of the section it concerns.
    asked = _asked(set_id, row)
    scene = _scene(set_id, row, store.set_sections(set_id), asked)
    scene["flags"] = specs_inputs.flags(report, language, CHECKS, KINDS, asked, store.ADVICE)
    return render_template("specs/check.html", spec=row, report=report, checks=CHECKS, scene=scene,
                           chosen=store.chosen_for(row), is_admin=_is_admin(),
                           amending=request.args.get("amend", ""), shown=request.args.get("shown", ""),
                           fmt=request.args.get("fmt") or "",
                           issuing=request.args.get("issuing"), blocking=_not_issued(report),
                           language=language, kinds=KINDS,
                           waiting=store.open_items(set_id, report))


@bp.post("/sets/<int:set_id>/fix")
@login_required
def fix_set(set_id: int):
    _set_or_404(set_id)
    how = {k: request.form.get(k, "") for k in ("old", "new", "name", "value", "property", "row_id")}
    try:
        count = store.fix_set(set_id, request.form.get("action", ""), **how)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count), "success" if count else "error")
    return redirect(url_for("specs.check_set", set_id=set_id))


@bp.get("/library/check")
@login_required
def check_library():
    family = request.args.get("family") or None
    return render_template("specs/check.html", spec=None, report=store.check_library(family),
                           checks=CHECKS, chosen=store.chosen_for(None), is_admin=_is_admin(),
                           language=_language(store.language_library()), kinds=KINDS,
                           family=family)


@bp.post("/library/fix")
@login_required
def fix_library():
    if not _admin_only():
        return redirect(url_for("specs.check_library"))
    how = {k: request.form.get(k, "") for k in ("old", "new", "name", "value", "property")}
    try:
        count = store.fix_library(request.form.get("action", ""),
                                  family=request.form.get("family") or None, **how)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
    return redirect(url_for("specs.check_library", family=request.form.get("family") or None))


KINDS = [
    ("spelling", "Spelling", True),
    ("grammar", "Grammar", False),
    ("english", "UK or US English", True),
    ("units", "SI units", True),
    ("scope", "Wording for the project's scope", True),
    ("wording", "The office's wording", True),
]


def _language(found: list[dict]) -> dict[str, list[dict]]:
    """Suggestions under their kind, the same change in several places as one."""
    grouped: dict[str, dict[tuple, dict]] = {k: {} for k, _t, _a in KINDS}
    for f in found:
        if not f["old"]:
            key: tuple = (id(f),)
        elif f["kind"] == "grammar":
            key = (f["old"], f["new"], f["message"])
        else:                                           # "Fiber" and "fiber" are one change
            key = (f["old"].lower(), f["new"].lower())
        one = grouped[f["kind"]].setdefault(key, {"old": f["old"], "new": f["new"],
                                                   "message": f["message"], "places": []})
        one["places"].append(f)
    return {k: list(v.values()) for k, v in grouped.items()}


@bp.post("/sets/<int:set_id>/language")
@login_required
def language_set(set_id: int):
    _set_or_404(set_id)
    back = url_for("specs.check_set", set_id=set_id) + "#language"
    action, kind = request.form.get("action"), request.form.get("kind", "")
    old, new = request.form.get("old") or None, request.form.get("new")
    if action == "all":
        count = store.accept_all_set(set_id, kind, old, new if old else None)
        flash(_fixed(count), "success" if count else "error")
        return redirect(back)
    if action == "reject_all":
        n = store.reject_all(set_id, store.language_set(set_id), kind)
        flash(_rejected(n, "this specification"), "success")
        return redirect(back)
    if action == "leave":
        store.ignore(set_id, request.form.get("old", ""))
        flash(f"\"{request.form.get('old', '').strip()}\" is left as it is in this specification.", "success")
        return redirect(back)
    try:
        count = store.accept_set(set_id, request.form)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count) if count else "That text has changed since; nothing was changed.",
              "success" if count else "error")
    return redirect(back)


@bp.post("/library/language")
@login_required
def language_library():
    back = url_for("specs.check_library") + "#language"
    if not _admin_only():
        return redirect(back)
    action, kind = request.form.get("action"), request.form.get("kind", "")
    old, new = request.form.get("old") or None, request.form.get("new")
    if action == "all":
        count = store.accept_all_library(kind, old, new if old else None)
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
        return redirect(back)
    if action == "reject_all":
        n = store.reject_all(0, store.language_library(), kind)
        flash(_rejected(n, "the library"), "success")
        return redirect(back)
    if action == "leave":
        store.ignore(0, request.form.get("old", ""))
        flash(f"\"{request.form.get('old', '').strip()}\" is left as it is in the library.", "success")
        return redirect(back)
    try:
        count = store.accept_library(request.form)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
    return redirect(back)


def _rejected(n: int, where: str) -> str:
    return (f"Rejected: {n} suggestion{'s' if n != 1 else ''} will not be made again in {where}."
            if n else "There was nothing to reject.")


def _fixed(count: int) -> str:
    return (f"Changed {count} place{'s' if count != 1 else ''}." if count
            else "Nothing needed changing.")


# --- the library as one file -------------------------------------------------------------

@bp.get("/library/file")
@login_required
def library_file():
    return Response(store.pack(), mimetype="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="specs-library.zip"'})


@bp.post("/library/file")
@login_required
def load_library_file():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    files = _uploads("library")
    if files:
        filename, data = files[0]
        mode = request.form.get("mode", "update")
        if mode == "replace" and request.form.get("sure") != "yes":
            flash("Tick that you mean to take out the sections the file does not have, "
                  "or choose another way to load it.", "error")
            return redirect(url_for("specs.library", family=request.form.get("family") or None))
        try:
            counted = store.unpack(data, mode)
        except specs.SpecError as exc:
            flash(f"{filename}: {exc}", "error")
        else:
            flash(_loaded(filename, counted), "success")
    return redirect(url_for("specs.library", family=request.form.get("family") or None))


def _loaded(filename: str, counted: dict) -> str:
    """What a library file load did, as the page says it."""
    said = [f"{counted['added']} new section{'s' if counted['added'] != 1 else ''}"]
    if counted["updated"]:
        said.append(f"{counted['updated']} updated to a new version")
    if counted["same"]:
        said.append(f"{counted['same']} already the same")
    if counted["kept"]:
        said.append(f"{counted['kept']} already here and left as they are")
    if counted["removed"]:
        said.append(f"{len(counted['removed'])} taken out ({', '.join(counted['removed'])})")
    return (f"Read {filename}: " + "; ".join(said) + f". {counted['options']} questions, "
            f"{counted['variables']} words and {counted['standards']} new standards."
            + (" Projects keep their own copies of the sections taken out."
               if counted["removed"] else ""))


# The same load with its progress shown (spec-progress.js): the file is sent and
# put by as a pending load, then read in a few sections per call. Each answer is
# JSON; "go" is where the page goes next, with what happened flashed there.

@bp.post("/library/file/begin")
@login_required
def begin_library_load():
    go = url_for("specs.library", family=request.form.get("family") or None)
    if not _admin_only():
        return jsonify(go=go)
    files = _uploads("library")
    if not files:
        if not request.files.get("library"):
            flash("Choose the library file (.zip) first.", "error")
        return jsonify(go=go)
    filename, data = files[0]
    mode = request.form.get("mode", "update")
    if mode == "replace" and request.form.get("sure") != "yes":
        flash("Tick that you mean to take out the sections the file does not have, "
              "or choose another way to load it.", "error")
        return jsonify(go=go)
    try:
        begun = store.begin_load(data, mode, filename)
    except specs.SpecError as exc:
        flash(f"{filename}: {exc}", "error")
        return jsonify(go=go)
    return jsonify(id=begun["id"], done=0, total=begun["total"], message="Reading the sections in.",
                   step=url_for("specs.step_library_load", load_id=begun["id"],
                                family=request.form.get("family") or None))


@bp.post("/library/file/step/<load_id>")
@login_required
def step_library_load(load_id: str):
    go = url_for("specs.library", family=request.args.get("family") or None)
    if not _admin_only():
        store.drop_load(load_id)
        return jsonify(go=go, failed=True)
    try:
        step = store.step_load(load_id, seconds=0.5, most=8)
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return jsonify(go=go, failed=True, message=str(exc))
    answer = {k: step[k] for k in ("done", "total", "message", "finished")}
    if step["finished"]:
        flash(_loaded(step["filename"], step["counted"]), "success")
        answer["go"] = go
    return jsonify(answer)


@bp.post("/library/delete")
@login_required
def delete_library_sections():
    """The ticked sections taken out of the master library."""
    family = request.form.get("family") or None
    if not _admin_only():
        return redirect(url_for("specs.library", family=family))
    gone = store.delete_sections(int(v) for v in request.form.getlist("section_id") if v.isdigit())
    if gone:
        flash(f"Took {len(gone)} section{'s' if len(gone) != 1 else ''} out of the library: "
              + ", ".join(f"{s['number']}" for s in gone)
              + ". Projects keep their own copies.", "success")
    else:
        flash("Tick the sections to take out first.", "error")
    return redirect(url_for("specs.library", family=family))


# Review, approval and issue control: its routes join this blueprint.
from . import specs_review_views  # noqa: E402,F401
# The issued specifications, amendments for the MTD and the standards register.
from . import specs_issued_views  # noqa: E402,F401
# Packages of one project, and the differences between what they issue.
from . import specs_packages_views  # noqa: E402,F401
# The start page's dashboard, a new project's page, and .themis files in and out.
from . import specs_home_views  # noqa: E402,F401
