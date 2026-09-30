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
import zipfile

from flask import (
    Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for,
)
from markupsafe import Markup, escape

from .. import specs, specs_check
from .. import specs_store as store
from ..auth import login_required

bp = Blueprint("specs", __name__, url_prefix="/specs")

# A specification section is a few hundred kilobytes; a house template with a
# logo in its header a few more. Twelve megabytes is room for a batch of them.
MOST = 12 * 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@bp.app_template_filter("spectext")
def spectext(text: str, values: dict | None = None, reader=None, here: str = "") -> Markup:
    """A paragraph as it reads for the project: each filled-in word marked,
    each cross-reference written out as it stands now, and — given a reader
    that knows the project's basis — each standard on that basis."""
    values = values or {}
    text = text or ""
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
        out.append(escape(text[last:match.start()]))
        name = match.group(1)
        if values.get(name):
            out.append(Markup('<span class="spec-var" title="{{%s}}">%s</span>')
                       % (name, values[name]))
        else:
            out.append(Markup('<span class="spec-var" title="No value yet">%s</span>')
                       % match.group(0))
        last = match.end()
    out.append(escape(text[last:]))
    return Markup("").join(out)


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


def _uploads(field: str) -> list[tuple[str, bytes]]:
    """The Word files sent, each read in full; anything too big is refused."""
    out = []
    for upload in request.files.getlist(field):
        if not upload or not upload.filename:
            continue
        data = upload.read(MOST + 1)
        if len(data) > MOST:
            flash(f"{upload.filename} is too big to read here — 12 MB is the limit.", "error")
            continue
        out.append((upload.filename, data))
    return out


def _docx_response(data: bytes, name: str) -> Response:
    return Response(data, mimetype=DOCX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- the front page -------------------------------------------------------------

@bp.get("/")
@login_required
def index():
    return render_template("specs/index.html", sets=store.sets(), library=store.library(),
                           is_admin=_is_admin())


@bp.post("/sets")
@login_required
def new_set():
    try:
        set_id = store.create_set(request.form, copy_from=request.form.get("copy_from", type=int))
    except specs.SpecError as exc:
        flash(str(exc), "error")
        return redirect(url_for("specs.index"))
    flash("Specification started. Fill in its header, make its choices, then add sections.",
          "success")
    return redirect(url_for("specs.spec_set", set_id=set_id))


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
    report = store.check_set(set_id) if sections else None
    return render_template(
        "specs/set.html", spec=row, sections=sections, groups=_grouped(store.options()),
        chosen=chosen, picked={k: set(v.split("|")) for k, v in chosen.items()},
        variables=store.variables(), values=values,
        available=[s for s in store.library() if s["id"] not in have],
        missing=missing, is_admin=_is_admin(), report=report)


def _grouped(options: list[dict]) -> list[tuple[str, list[dict]]]:
    """The questions under their headings, in the order they were set out."""
    groups: dict[str, list[dict]] = {}
    for o in options:
        groups.setdefault(o.get("grp") or "Other", []).append(o)
    return list(groups.items())


@bp.post("/sets/<int:set_id>")
@login_required
def save_set(set_id: int):
    _set_or_404(set_id)
    chosen = {o["key"]: "|".join(request.form.getlist(f"opt_{o['key']}")) if o["kind"] == "many"
              else request.form.get(f"opt_{o['key']}", "") for o in store.options()}
    values = {v["key"]: request.form.get(f"var_{v['key']}", "") for v in store.variables()}
    try:
        store.update_set(set_id, request.form, chosen, values)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash("Saved.", "success")
    return redirect(url_for("specs.spec_set", set_id=set_id))


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
    added = store.add_sections(set_id, picked)
    flash(f"Added {added} section{'s' if added != 1 else ''} from the library."
          if added else "Tick the sections to add first.", "success" if added else "error")
    return redirect(url_for("specs.spec_set", set_id=set_id))


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
    missing = _not_issued(store.check_set(set_id))
    if missing and not request.args.get("anyway"):
        flash(f"Not issued yet: {len(missing)} reference{'s' if len(missing) != 1 else ''} point at "
              "sections or paragraphs this specification does not issue. Add the sections, or "
              "correct the references, then issue — or issue anyway from the top of this page.",
              "error")
        return redirect(url_for("specs.check_set", set_id=set_id, issuing=1))
    chosen, values, template = store.chosen_for(row), store.values_for(row), store.template_bytes()
    reader = store.reader(store.set_whole(set_id), chosen)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for s in sections:
            data = specs.write_docx(s, specs.loads(s["body"]), row, chosen, values, template,
                                    resolve=reader.issued(s["number"]))
            bundle.writestr(specs.file_name(row["file_pattern"], s), data)
    name = "".join(c if c.isalnum() or c in "-_ " else "-" for c in (row["code"] or row["name"]))
    return Response(buffer.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="{name.strip() or "specification"} - '
                             f'specification REV {row["revision"]}.zip"'})


def _not_issued(report: dict) -> list[dict]:
    """References that would go out pointing at nothing this issue contains."""
    return [i for i in report["references"] if "not in this specification" in i["message"]
            or i["severity"] == "error"]


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
    return render_template(
        "specs/section.html", spec=row, section=s, rows=_rows(nodes, chosen, base),
        compared=base is not None, values=store.values_for(row), is_admin=_is_admin(),
        options=store.options(), chosen=chosen,
        reader=store.reader(store.set_whole(set_id), chosen),
        master=store.section(s["section_id"]) if s["section_id"] else None)


@bp.route("/sets/<int:set_id>/sections/<int:row_id>/edit", methods=["GET", "POST"])
@login_required
def edit_set_section(set_id: int, row_id: int):
    row = _set_or_404(set_id)
    s = _set_section_or_404(set_id, row_id)
    if request.method == "POST":
        text = request.form.get("text", "")
        nodes = specs.align(specs.loads(s["body"]), specs.from_text(text))
        store.save_set_section(set_id, row_id, nodes, title=request.form.get("title"),
                               doc_code=request.form.get("doc_code"))
        flash("Saved. Anything that differs from the master is marked.", "success")
        return redirect(url_for("specs.set_section", set_id=set_id, row_id=row_id))
    return render_template(
        "specs/edit.html", spec=row, section=s, text=specs.to_text(specs.loads(s["body"])),
        options=store.options(), variables=store.variables(), library=False)


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
            store.remove_set_section(set_id, row_id)
            flash(f"Took section {s['number']} out of this specification.", "success")
            return redirect(url_for("specs.spec_set", set_id=set_id))
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
    data = specs.write_docx(s, specs.loads(s["body"]), row, chosen, store.values_for(row),
                            store.template_bytes(), resolve=reader.issued(s["number"]))
    return _docx_response(data, specs.file_name(row["file_pattern"], s))


# --- the library ------------------------------------------------------------------

@bp.get("/library")
@login_required
def library():
    return render_template("specs/library.html", sections=store.library(),
                           template=store.template_row(), is_admin=_is_admin())


@bp.post("/library/upload")
@login_required
def upload_to_library():
    if not _admin_only():
        return redirect(url_for("specs.library"))
    done = []
    for filename, data in _uploads("files"):
        try:
            _section_id, how = store.import_to_library(filename, data)
        except specs.SpecError as exc:
            flash(f"{filename}: {exc}", "error")
            continue
        done.append(f"{filename} ({how})")
    if done:
        flash("Read " + ", ".join(done) + ". Check each one reads right before a project "
              "takes it.", "success")
    return redirect(url_for("specs.library"))


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
                                        request.form.get("title", ""), starter, note="Started")
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
        reader=store.reader(store.library_whole(), _every_choice(), standards=False),
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
        nodes = specs.align(specs.loads(s["body"]), specs.from_text(request.form.get("text", "")))
        try:
            store.save_section(request.form.get("number", s["number"]),
                               request.form.get("title", s["title"]), nodes,
                               note=request.form.get("note", "").strip(), section_id=section_id)
        except specs.SpecError as exc:
            flash(str(exc), "error")
            return redirect(url_for("specs.edit_library_section", section_id=section_id))
        flash("Saved as a new version. Projects that took the last one can bring this in.",
              "success")
        return redirect(url_for("specs.library_section", section_id=section_id))
    return render_template(
        "specs/edit.html", spec=None, section=s, text=specs.to_text(specs.loads(s["body"])),
        options=store.options(), variables=store.variables(), library=True)


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
    reader = store.reader(store.library_whole(), chosen, standards=False)
    data = specs.write_docx(s, specs.loads(s["body"]), {"revision": ""}, chosen,
                            {v["key"]: v["default_value"] for v in store.variables()},
                            store.template_bytes(), resolve=reader.issued(s["number"]))
    return _docx_response(data, specs.file_name("SPC-{number}", s))


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
    if files:
        filename, data = files[0]
        try:
            store.save_template(filename, data)
        except specs.SpecError as exc:
            flash(str(exc), "error")
        else:
            flash(f"Every section now goes out in {filename}'s styles, page and header.", "success")
    return redirect(url_for("specs.library"))


@bp.post("/template/delete")
@login_required
def delete_template():
    if _admin_only():
        store.drop_template()
        flash("Back to the built-in template.", "success")
    return redirect(url_for("specs.library"))


@bp.get("/template")
@login_required
def download_template():
    row = store.template_row()
    data = store.template_bytes() or specs.TEMPLATE.read_bytes()
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
    ("references", "Cross-references",
     "References to sections, articles and paragraphs that are not there, or not issued."),
    ("outdated", "Outdated standards", "Standards cited that have been withdrawn or superseded."),
    ("standards", "Standards off the project's basis",
     "Citations the project's basis cannot convert, because no equivalent is recorded."),
    ("discrepancies", "Discrepancies",
     "The same property given different values, sections cited under the wrong title, "
     "a standard cited in two editions."),
    ("repeated", "Repeated", "Values written out many times, and paragraphs said more than once."),
    ("setup", "Set-up", "Conditions naming questions or answers that do not exist, and words "
                        "with no value."),
]


@bp.get("/sets/<int:set_id>/check")
@login_required
def check_set(set_id: int):
    row = _set_or_404(set_id)
    report = store.check_set(set_id)
    return render_template("specs/check.html", spec=row, report=report, checks=CHECKS,
                           chosen=store.chosen_for(row), is_admin=_is_admin(),
                           issuing=request.args.get("issuing"), blocking=_not_issued(report),
                           language=_language(store.language_set(set_id)), kinds=KINDS)


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
    return render_template("specs/check.html", spec=None, report=store.check_library(),
                           checks=CHECKS, chosen=store.chosen_for(None), is_admin=_is_admin(),
                           language=_language(store.language_library()), kinds=KINDS)


@bp.post("/library/fix")
@login_required
def fix_library():
    if not _admin_only():
        return redirect(url_for("specs.check_library"))
    how = {k: request.form.get(k, "") for k in ("old", "new", "name", "value", "property")}
    try:
        count = store.fix_library(request.form.get("action", ""), **how)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
    return redirect(url_for("specs.check_library"))


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
    if request.form.get("action") == "all":
        count = store.accept_all_set(set_id, request.form.get("kind", ""))
        flash(_fixed(count), "success" if count else "error")
        return redirect(back)
    if request.form.get("action") == "leave":
        store.ignore(set_id, request.form.get("old", ""))
        flash(f"\"{request.form.get('old')}\" is left as it is in this specification.", "success")
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
    if request.form.get("action") == "all":
        count = store.accept_all_library(request.form.get("kind", ""))
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
        return redirect(back)
    if request.form.get("action") == "leave":
        store.ignore(0, request.form.get("old", ""))
        flash(f"\"{request.form.get('old')}\" is left as it is in the library.", "success")
        return redirect(back)
    try:
        count = store.accept_library(request.form)
    except specs.SpecError as exc:
        flash(str(exc), "error")
    else:
        flash(_fixed(count) + (" Each section changed was saved as a new version." if count else ""),
              "success" if count else "error")
    return redirect(back)


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
        try:
            counted = store.unpack(data)
        except specs.SpecError as exc:
            flash(f"{filename}: {exc}", "error")
        else:
            flash(f"Read {filename}: {counted['sections']} sections, {counted['options']} questions, "
                  f"{counted['variables']} words and {counted['standards']} standards.", "success")
    return redirect(url_for("specs.library"))
