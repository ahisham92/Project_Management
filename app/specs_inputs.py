"""The inputs of a project at a glance, before it is issued: every answer the
engineer gave (or left to a suggestion, or has not given) placed on a picture
of the works as they are built, station by station in the order of the
questions' story, each with the words of the specification it goes into.

The page draws the picture in the browser from what ``scene`` returns; the
same data is shown as a plain summary underneath, which is what is read
without scripts or when printed."""

from __future__ import annotations

import re
from typing import Any, Mapping

from . import specs_questions

# Where each chapter of the story stands on the picture. The ingredients are
# split by what they are, so the sand is its own heap and the cement its silo.
STATIONS = [
    # id, chapter, name, what it shows
    ("office", "the-project", "Site office", "The project, its site and who is who."),
    ("documents", "before-work-starts", "Submittals", "What is submitted and agreed before work starts."),
    ("shoring", "preparing-the-site", "Shoring and monitoring", "Demolition, temporary works and monitoring."),
    ("cement", "the-ingredients", "Cement silo", "Cement and the cementitious materials that go with it."),
    ("sand", "the-ingredients", "Sand", "Fine aggregate."),
    ("gravel", "the-ingredients", "Coarse aggregate", "Stone, gravel and lightweight aggregate."),
    ("water", "the-ingredients", "Water", "Mixing water."),
    ("admixtures", "the-ingredients", "Admixtures and fibres", "Admixtures, fibres and pigments dosed into the mix."),
    ("store", "the-ingredients", "Materials store", "Joint fillers, retarders and the other materials."),
    ("mixer", "the-mix", "Mixer", "Each element's concrete: class, strength, exposure, w/c, slump, air."),
    ("formwork", "the-moulds", "Formwork", "The moulds and what is cast into them."),
    ("rebar", "the-steel-inside", "Reinforcement", "Bars, mesh, post-tensioning and precast units."),
    ("pour", "the-pour", "The pour", "Placing, finishing and curing."),
    ("frame", "the-steel-frame", "Steel frame", "Structural steel, decking, stairs and railings."),
    ("membrane", "keeping-water-out", "Waterproofing", "Membranes and waterstops."),
    ("bridge", "bridges", "Bridge", "What the bridge asks."),
    ("lab", "proving-it", "Testing lab", "Tests, inspections and results."),
    ("repair", "looking-after-it", "Maintenance", "Repair and maintenance in service."),
    ("other", "other-details", "Other details", "Questions placed in no chapter."),
]
INGREDIENT = [
    ("admixtures", re.compile(r"admix|fibre|fiber|pigment|retard|plastici|accelerat|air.?entrain|inhibit", re.I)),
    ("cement", re.compile(r"cement|scm|fly.?ash|slag|ggbs|silica|pozzolan|pfa|c3a", re.I)),
    ("sand", re.compile(r"sand|fine.?aggregate", re.I)),
    ("gravel", re.compile(r"aggregate|gravel|stone|lwa", re.I)),
    ("water", re.compile(r"water", re.I)),
]
SENTENCES = 3          # words of the specification shown for each answer
SENTENCE_CHARS = 320


def station_of(q: Mapping[str, Any], chapter: str) -> str:
    """Where a question stands on the picture."""
    if chapter == "the-ingredients":
        said = f"{q['key']} {q['label']}"
        return next((sid for sid, words in INGREDIENT if words.search(said)), "store")
    return next((s[0] for s in STATIONS if s[1] == chapter), "other")


def _state(q: Mapping[str, Any]) -> str:
    if q["answered"]:
        return "answered"
    return "needed" if q.get("suggested") is None else "suggested"


def _words(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SENTENCE_CHARS else text[:SENTENCE_CHARS - 1].rstrip() + "…"


def scene(questions: list[dict], words: list[dict], element_labels: Mapping[str, str],
          place_url) -> dict:
    """The picture's data: its stations with their questions and answers, the
    chapters they follow, the per-element table of the mix and the totals.

    ``questions`` are what ``specs_questions.asked`` gives; ``words`` the
    sections as the files say them (``specs_review.issued_words(..., marked=True)``);
    ``place_url(row_id, node_id)`` links a paragraph."""
    said = {(s["row_id"], n["id"]): n["text"] for s in words for n in s["nodes"]}
    chapters = specs_questions.story(questions)
    stations = {sid: {"id": sid, "chapter": ch, "name": name, "what": what, "questions": [],
                      "answered": 0, "suggested": 0, "needed": 0}
                for sid, ch, name, what in STATIONS}
    mix_rows: dict[str, dict[str, str]] = {}
    mix_cols: list[dict] = []
    for c in chapters:
        for q in c["questions"]:
            state = _state(q)
            value = q["answer"] if q["answered"] else q.get("suggested")
            rows = []
            if q["rows"]:
                for e in q["rows"]:
                    own = q["row_answers"].get(e)
                    shown = (specs_questions.shown(q, own) if q["split"] and own is not None
                             else specs_questions.shown(q, value) if value is not None else "")
                    rows.append({"element": element_labels.get(e, e.replace("_", " ").capitalize()),
                                 "value": shown})
            places = []
            for p in q["places"]:
                text = said.get((p["row_id"], p["node_id"]))
                if text is None:
                    continue
                places.append({"section": p["number"], "label": p["label"], "article": p["article"],
                               "url": place_url(p["row_id"], p["node_id"]), "words": _words(text)})
                if len(places) == SENTENCES:
                    break
            item = {"key": q["key"], "label": q["label"], "state": state,
                    "value": specs_questions.shown(q, value) if value is not None else "",
                    "split": bool(q["split"]), "rows": rows, "places": places,
                    "sections": q["sections"], "switch": bool(q.get("switch"))}
            sid = station_of(q, c["slug"])
            st = stations[sid]
            st["questions"].append(item)
            st[state] += 1
            if c["slug"] == "the-mix" and rows:
                mix_cols.append({"key": q["key"], "label": q["label"], "state": state})
                for r in rows:
                    mix_rows.setdefault(r["element"], {})[q["key"]] = r["value"]
    shown_stations = [s for s in stations.values() if s["questions"]]
    totals = {k: sum(s[k] for s in shown_stations) for k in ("answered", "suggested", "needed")}
    out_chapters = []
    for c in chapters:
        held = [s for s in shown_stations if s["chapter"] == c["slug"]]
        needed, suggested = sum(s["needed"] for s in held), sum(s["suggested"] for s in held)
        out_chapters.append({"slug": c["slug"], "number": c["number"], "name": c["name"], "lead": c["lead"],
                             "stations": [s["id"] for s in held], "needed": needed, "suggested": suggested,
                             "done": not needed and not suggested})
    # The stages open in turn: a chapter opens once every one before it is
    # answered, a suggestion counting once the engineer accepts it.
    open_stage = next((i for i, c in enumerate(out_chapters) if not c["done"]), len(out_chapters))
    for i, c in enumerate(out_chapters):
        c["stage"] = i
        c["locked"] = i > open_stage
        for sid in c["stations"]:
            stations[sid]["stage"] = i
            stations[sid]["locked"] = c["locked"]
    return {"stations": shown_stations, "chapters": out_chapters, "open_stage": open_stage,
            "mix": {"columns": mix_cols, "rows": [{"element": e, "values": v} for e, v in mix_rows.items()]},
            "totals": totals, "count": sum(totals.values())}


def station_questions(questions: list[dict], station: str) -> tuple[dict | None, list[dict]]:
    """The chapter a station stands in, and its questions as ``asked`` gives
    them, to answer there."""
    for c in specs_questions.story(questions):
        held = [q for q in c["questions"] if station_of(q, c["slug"]) == station]
        if held:
            return c, held
    return None, []


def blocking(data: Mapping[str, Any], station: str) -> dict | None:
    """What keeps a station locked: the first chapter not yet answered, with how
    many are left there and a station of it to go to; None when it is open."""
    st = next((s for s in data["stations"] if s["id"] == station), None)
    if st is None or not st.get("locked"):
        return None
    c = data["chapters"][data["open_stage"]]
    by_id = {s["id"]: s for s in data["stations"]}
    first = next((sid for sid in c["stations"] if by_id[sid]["needed"] or by_id[sid]["suggested"]),
                 c["stations"][0])
    return {"number": c["number"], "name": c["name"], "left": c["needed"] + c["suggested"], "station": first}
