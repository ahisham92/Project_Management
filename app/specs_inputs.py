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
    ("decide", "deciding", "The brief", "What the project builds, its elements and the systems it uses. "
     "Decided first: the site is drawn from it."),
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
    ("rebar", "the-steel-inside", "Reinforcement", "Bars, mesh, couplers and the cage."),
    ("tendons", "the-steel-inside", "Post-tensioning", "Tendons, ducts, anchorages and stressing."),
    ("precast", "the-steel-inside", "Precast yard", "Precast and prestressed units, made, stored and lifted in."),
    ("pour", "the-pour", "The pour", "Placing, finishing and curing."),
    ("frame", "the-steel-frame", "Steel frame", "Structural steel, decking, stairs and railings."),
    ("membrane", "keeping-water-out", "Waterproofing", "Membranes and waterstops."),
    ("bridge", "bridges", "Bridge", "What the bridge asks."),
    ("lab", "proving-it", "Testing lab", "Tests, inspections and results."),
    ("repair", "looking-after-it", "Maintenance", "Repair and maintenance in service."),
    ("other", "other-details", "Other details", "Questions placed in no chapter."),
    # The geotechnical works, along the geotechnical story.
    ("g_investigation", "knowing-the-ground", "Boreholes and surveys", "The drilling rig, the boreholes, "
     "in-situ tests and the surveys of the ground and the seabed."),
    ("g_earthworks", "preparing-the-ground", "Earthworks", "Clearing, excavation, fill, compaction, "
     "blasting and the liners and drains in the ground."),
    ("g_improvement", "improving-the-ground", "Ground improvement", "Vertical drains, compaction, "
     "stone columns, soil mixing, jet grouting and rigid inclusions."),
    ("g_retaining", "holding-the-ground", "Retaining and excavation support", "Diaphragm and embedded "
     "walls, soil nails, anchors, MSE walls, gabions and slopes."),
    ("g_piles", "into-the-ground", "Piling rig", "Bored, driven and micro piles, and their load and "
     "integrity tests."),
    ("g_marine", "by-the-sea", "Marine works", "Dredging, reclamation, revetments, breakwaters, "
     "jetties, groynes, scour protection and buoys."),
    ("g_tunnels", "through-the-ground", "Tunnel", "The TBM or mined heading, the support, the lining "
     "and the grouting."),
    ("g_dams", "holding-water", "Dam", "The dam's foundation, fill, protection, grouting and RCC."),
    ("g_pavements", "on-the-ground", "Pavements", "Subbase, base, asphalt and concrete paving."),
    ("g_materials", "ground-materials", "Materials store", "Concrete, grout, steel, aggregates and "
     "geosynthetics for the ground works."),
    ("g_monitoring", "watching-it", "Instruments", "Piezometers, inclinometers, settlement plates "
     "and survey points."),
]
INGREDIENT = [
    ("admixtures", re.compile(r"admix|fibre|fiber|pigment|retard|plastici|accelerat|air.?entrain|inhibit", re.I)),
    ("cement", re.compile(r"cement|scm|fly.?ash|slag|ggbs|silica|pozzolan|pfa|c3a", re.I)),
    ("sand", re.compile(r"sand|fine.?aggregate", re.I)),
    ("gravel", re.compile(r"aggregate|gravel|stone|lwa", re.I)),
    ("water", re.compile(r"water", re.I)),
]
STEEL_INSIDE = [
    ("tendons", re.compile(r"post.?tension|tendon|strand|duct|anchorage|stress|grout|sheath", re.I)),
    ("precast", re.compile(r"precast|pre.?cast|hollow.?core|tilt|double.?tee|prestress|plant.?cast", re.I)),
]
# Each level told as the story of the works: what is happening on site when
# its questions come up. {works} is what the project builds ("the building",
# "the quay", "the bridge" or "the works"), {elements} its elements.
NARRATIVE = {
    "deciding": "Every project starts at the drawing board. Decide what {works} is, the elements it "
                "has and the systems it uses: the site in the picture is drawn from these choices, "
                "and every level after follows from them.",
    "the-project": "The site office opens. Here the specification learns where {works} stands, who "
                   "the client, the engineer and the contractor are, and what this package covers.",
    "before-work-starts": "Nothing is built yet. The contractor brings the drawings, method statements, "
                          "samples and programme, and they are agreed before the first work on site.",
    "preparing-the-site": "The ground is made ready for {works}: what stays is held up, what goes is "
                          "taken down, and every movement is watched while the work goes on.",
    "the-moulds": "The formwork goes up for {elements}. Its shape, its finish and what is cast into it "
                  "are settled here, before any steel or concrete arrives.",
    "the-steel-inside": "The steel goes into the moulds: the bars and the cage{extras}. What the steel "
                        "is, how it is fixed and how much cover it gets are settled before the concrete.",
    "the-ingredients": "At the batch plant the cement silo, the sand and stone heaps, the water and the "
                       "admixtures are stocked. Each ingredient is specified before anything is mixed.",
    "the-mix": "The mixer turns. Each element's concrete gets its class, strength, exposure, "
               "water/cement ratio, slump and air, and the truck takes it down the road to the pump.",
    "the-pour": "The pump reaches over the formwork and the concrete goes in. How it is placed, "
                "compacted, finished and cured decides the surface {works} will keep.",
    "proving-it": "{specimens} go to the lab. Tests and inspections prove what was built, and this "
                  "level says what happens when a result falls short.",
    "the-steel-frame": "The steel frame rises on the concrete: the members and their connections, "
                       "decking, stairs and railings, and how they are protected.",
    "keeping-water-out": "Membranes and waterstops keep {works} dry: where water could get in, this "
                         "level says what stops it.",
    "bridges": "Out on the bridge: its bearings, joints and parapets, and what a bridge asks beyond "
               "the rest.",
    "looking-after-it": "{Works} is in service. Repairs and maintenance are planned so it keeps doing "
                        "its job for its design life.",
    "other-details": "A few questions the library does not place on the way. Answer them to finish "
                     "the story.",
    "knowing-the-ground": "The drilling rig arrives before anything else. Boreholes, in-situ tests and "
                          "surveys say what the ground under {works} is, and how it is to be reported.",
    "preparing-the-ground": "The site is cleared and the ground is dug, filled and compacted for {works}: "
                            "what goes in, in what layers, and how dense it must be.",
    "improving-the-ground": "Where the ground is too weak for {works}, it is made stronger: drains, "
                            "compaction, columns, mixing or grouting, and how much better it must be.",
    "holding-the-ground": "Walls, nails and anchors hold the sides of the excavation and the slopes "
                          "while {works} is built, and every movement is watched.",
    "into-the-ground": "The piling rig goes in. The piles that carry {works} down to firm ground are "
                       "drilled or driven, and loaded to prove they carry what they must.",
    "by-the-sea": "Out at the shore the dredgers and the barges work: the seabed is dredged, the land is "
                  "reclaimed, and armour rock protects the edge of {works}.",
    "through-the-ground": "The tunnel goes through the ground: how it is excavated, supported, lined "
                          "and grouted.",
    "holding-water": "The dam holds the water back: its foundation, its fill and its faces, and how "
                     "the rock under it is grouted.",
    "on-the-ground": "The roads and hardstandings go down in layers: the subbase, the base and the "
                     "surface, each with its materials and its tests.",
    "ground-materials": "The materials store holds what goes into the ground works: concrete and grout, "
                        "steel, aggregates and geosynthetics, each specified before it is used.",
    "watching-it": "Instruments in the ground show how it and {works} move: what is installed, how "
                   "often it is read and when the readings call for action.",
}


def narrative(slug: str, site: Mapping[str, Any]) -> str:
    """A level's opening lines, told for this project's works."""
    built = [w for w, on in (("the building", site.get("building")), ("the quay", site.get("marine")),
                             ("the bridge", site.get("bridge"))) if on]
    # Before anything is picked the project is not yet a building or a quay.
    works = "the project" if not site.get("builds") else built[0] if len(built) == 1 else "the works"
    elements = [e for e in site.get("elements") or [] if e and e != "none"]
    extras = [w for w, on in ((" with its post-tensioning tendons", site.get("pt")),
                              (" and the precast units from the yard", site.get("precast"))) if on]
    text = NARRATIVE.get(slug) or ""
    if slug == "deciding" and site.get("trade") == "geotechnical":
        text = ("Every project starts at the drawing board. Decide what the ground works under {works} "
                "are and the ground they are in: the site in the picture is drawn from these choices, "
                "and every level after follows from them.")
    return text.format(
        works=works, Works=works[:1].upper() + works[1:],
        elements=specs_questions.joined(elements[:4]) if elements else "each element",
        extras="".join(extras),
        specimens="Cylinders" if site.get("specimens") == "cylinders" else "Cubes")


# The level before the questions: what the project is, decided first.
DECIDING = {"slug": "deciding", "number": 0, "name": "Deciding the project",
            "lead": "What the project builds, its elements, and the systems it uses: the site is "
                    "drawn from these, and the questions follow from them."}
DECIDED = "_decided"        # kept with the project's choices once the engineer has decided them
SENTENCES = 3          # words of the specification shown for each answer
SENTENCE_CHARS = 320


def station_of(q: Mapping[str, Any], chapter: str) -> str:
    """Where a question stands on the picture."""
    if chapter == "ground-materials" or chapter in GEO_CHAPTERS:
        return next((s[0] for s in STATIONS if s[1] == chapter), "other")
    return _structural_station(q, chapter)


GEO_CHAPTERS = {"knowing-the-ground", "preparing-the-ground", "improving-the-ground", "holding-the-ground",
                "into-the-ground", "by-the-sea", "through-the-ground", "holding-water", "on-the-ground",
                "watching-it"}


def _structural_station(q: Mapping[str, Any], chapter: str) -> str:
    """Where a question stands on the picture."""
    if chapter == "the-ingredients":
        said = f"{q['key']} {q['label']}"
        return next((sid for sid, words in INGREDIENT if words.search(said)), "store")
    if chapter == "the-steel-inside":
        said = f"{q['key']} {q['label']}"
        return next((sid for sid, words in STEEL_INSIDE if words.search(said)), "rebar")
    return next((s[0] for s in STATIONS if s[1] == chapter), "other")


def _state(q: Mapping[str, Any]) -> str:
    if q["answered"]:
        return "answered"
    return "needed" if q.get("suggested") is None else "suggested"


def _words(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SENTENCE_CHARS else text[:SENTENCE_CHARS - 1].rstrip() + "…"


def _picked(chosen: Mapping[str, str], key: str) -> list[str]:
    return [v.strip() for v in (chosen.get(key) or "").split("|") if v.strip()]


def _yes(chosen: Mapping[str, str], key: str) -> bool:
    return (chosen.get(key) or "").strip().lower() == "yes"


def _some(chosen: Mapping[str, str], key: str) -> str:
    """The first of a pick-several answer that is not "None", or ""."""
    return next((v for v in _picked(chosen, key) if v.lower() != "none"), "")


def site_of(chosen: Mapping[str, str] | None, trade: str = "structures") -> dict:
    """What the picture of the works is drawn with, from the project's
    decisions: what it builds (a building, a quay on the sea, a bridge), its
    elements, and whether it has steel framing, precast, post-tensioning,
    crane rails, shoring and the rest."""
    chosen = chosen or {}
    builds = [b.lower() for b in _picked(chosen, "structures")]
    elements = [e.lower() for e in _picked(chosen, "elements")]
    return {
        "building": any("building" in b for b in builds) or not builds,
        "builds": bool(builds),
        "marine": any("marine" in b for b in builds) or (chosen.get("exposure") or "").lower() == "marine",
        "bridge": any("bridge" in b for b in builds),
        "elements": elements,
        "steel": _yes(chosen, "steel_framing"),
        "precast": _some(chosen, "precast"),
        "pt": _some(chosen, "post_tensioning"),
        "cranes": _yes(chosen, "cranes"),
        "shoring": _yes(chosen, "shoring") or _yes(chosen, "demolition") or _yes(chosen, "monitoring"),
        "rebar": _picked(chosen, "rebar") or ["Uncoated"],
        "specimens": "cylinders" if (chosen.get("testing") or "").lower() == "cylinders" else "cubes",
        "underwater": _yes(chosen, "underwater"),
        "repair": _yes(chosen, "repair"),
        # The geotechnical works the brief picked, drawn on the ground.
        "trade": trade,
        "geo": {k: [v for v in _picked(chosen, f"ge_{k}") if v.lower() != "none"]
                for k in ("investigation", "earthworks", "improvement", "piles", "pile_tests", "retaining",
                          "pavements", "tunnels", "dams", "marine")},
        "groundwater": (chosen.get("ge_groundwater") or "").lower(),
    }


# The brief asks only what applies: a question here is asked once the answers
# it depends on say so (marine furniture for marine structures, the steel's
# details once there is a steel frame, and so on). key: (on, how, value), how
# being "has" (that answer ticked), "is" (that answer picked) or "some" (any
# answer but None or No); a list of them must all hold, and ANY([...], [...])
# holds when one of its lists does.
Condition = tuple[str, str, str]


class ANY(tuple):
    """Alternatives: any one of these lists of conditions will do."""

    def __new__(cls, *alternatives: list):
        return super().__new__(cls, alternatives)


BRIEF_WHEN: dict[str, Any] = {}
for _k in ("fenders", "bollards", "ladders", "floating_piers"):
    BRIEF_WHEN[_k] = ("structures", "has", "Marine structures")
for _k in ("bridge_items", "bridge_segmental", "bridge_load_cells", "bridge_contractor_design",
           "bridge_bespoke_parapet", "bridge_deck_surfacing"):
    BRIEF_WHEN[_k] = ("structures", "has", "Bridges")
for _k in ("steel_systems", "steel_protection", "fire", "aess", "steel_design"):
    BRIEF_WHEN[_k] = ("steel_framing", "is", "Yes")
BRIEF_WHEN["deck_design"] = ("steel_systems", "has", "Steel deck")
BRIEF_WHEN["cfs_delegated"] = ("steel_systems", "has", "Cold-formed framing")
BRIEF_WHEN["pt_delegated_design"] = ("post_tensioning", "some", "")
# Vapour inhibitor in the ducts: post-tensioning, or a bridge's prestressed girders.
BRIEF_WHEN["pt_vapor_inhibitor"] = ANY([("post_tensioning", "some", "")],
                                       [("bridge_items", "has", "Prestressed girders")])
# Transfer girders carry a building's columns: not a quay's or a bridge's.
BRIEF_WHEN["pt_transfer_girders"] = [("post_tensioning", "some", ""), ("structures", "has", "Buildings")]
BRIEF_WHEN["pt_encapsulation"] = ("post_tensioning", "has", "Unbonded")
BRIEF_WHEN["precast_delegated_design"] = ("precast", "some", "")
# Hollow-core and double-tee floors, faced and insulated wall panels and
# stadium risers are a building's precast, not a quay's or a bridge's.
for _k in ("precast_hollowcore", "precast_double_tee", "precast_thin_brick", "precast_stone_facing",
           "precast_insulated_panels", "precast_stadia"):
    BRIEF_WHEN[_k] = [("precast", "some", ""), ("structures", "has", "Buildings")]
for _k in ("demo_explosives", "demo_salvage", "demo_hazardous", "demo_prestressed"):
    BRIEF_WHEN[_k] = ("demolition", "is", "Yes")
BRIEF_WHEN["monitor_digital_twin"] = ("monitoring", "is", "Yes")
for _k in ("wp_installer_warranty", "wp_composite_system"):
    BRIEF_WHEN[_k] = ("waterproofing", "some", "")
# Plaza pavers over the membrane: a building's podium or plaza deck.
BRIEF_WHEN["wp_plaza_pavers"] = [("waterproofing", "some", ""), ("structures", "has", "Buildings")]
for _k in ("stair_railings", "stair_delegated"):
    BRIEF_WHEN[_k] = ("stairs", "some", "")
# Thermal-break connections cross a building's insulated envelope.
BRIEF_WHEN["thermal_break"] = ("structures", "has", "Buildings")
# The geotechnical brief: marine works for marine projects, pile tests once
# there are piles.
BRIEF_WHEN["ge_marine"] = ("structures", "has", "Marine structures")
BRIEF_WHEN["ge_pile_tests"] = ("ge_piles", "some", "")
for _k in ("ge_mar_si_by", "ge_mar_survey_by"):
    BRIEF_WHEN[_k] = ("ge_marine", "some", "")
BRIEF_WHEN["ge_ret_mse_design_basis"] = ("ge_retaining", "has", "Mechanically stabilised earth walls")


def brief_rule(key: str) -> list[list[Condition]]:
    """What ``key`` hangs on, as alternatives each of conditions that must
    all hold ([] when it is always asked)."""
    when = BRIEF_WHEN.get(key)
    if not when:
        return []
    if isinstance(when, ANY):
        return [list(alt) for alt in when]
    return [list(when)] if isinstance(when, list) else [[when]]


# The answers others hang on: on a brief not yet decided they start unpicked,
# so a steel frame, marine structures or precast are asked for, never assumed.
BRIEF_GATES = frozenset(c[0] for k in BRIEF_WHEN for alt in brief_rule(k) for c in alt)


def _holds(condition: Condition, chosen: Mapping[str, str], seen: frozenset) -> bool:
    on, how, value = condition
    if not brief_applies(on, chosen, seen):
        return False
    picked = _picked(chosen, on)
    if how == "has":
        return value in picked
    if how == "is":
        return (chosen.get(on) or "").strip() == value
    return any(p.lower() not in ("none", "no") for p in picked)


def brief_applies(key: str, chosen: Mapping[str, str] | None, _seen: frozenset = frozenset()) -> bool:
    """Whether the brief asks ``key`` for these choices: the answers it hangs
    on say so, and they are themselves asked."""
    rule = brief_rule(key)
    if not rule or key in _seen:
        return True
    chosen = chosen or {}
    return any(all(_holds(c, chosen, _seen | {key}) for c in alt) for alt in rule)


def scoped(chosen: Mapping[str, str], options: list[dict]) -> dict[str, str]:
    """The choices a project's text is written from: a decision the brief does
    not ask (marine furniture on a building, hollow-core floors on a quay, the
    steel's details with no steel) is off, whatever it was left at, so the
    paragraphs and questions that hang on it are not there. Off is its "None"
    or "No"; a decision with neither is not answered."""
    out = dict(chosen)
    for o in options:
        key = o["key"]
        if key not in BRIEF_WHEN or brief_applies(key, chosen):
            continue
        off = next((c for c in o.get("choice_list") or [] if c.strip().lower() in ("none", "no")), None)
        if off is None:
            out.pop(key, None)
        else:
            out[key] = off
    return out


def decisions(chosen: Mapping[str, str] | None, options: list[dict]) -> list[dict]:
    """The brief in words: each decision with what the project picked."""
    chosen = chosen or {}
    out = []
    for o in options:
        if not brief_applies(o["key"], chosen):
            continue                     # fenders on a building, steel details with no steel
        value = " · ".join(_picked(chosen, o["key"]))
        if value:
            out.append({"key": o["key"], "label": o["label"], "group": o.get("grp") or "", "value": value})
    return out


def scene(questions: list[dict], words: list[dict], element_labels: Mapping[str, str],
          place_url, chosen: Mapping[str, str] | None = None, decided: bool | None = None,
          options: list[dict] | None = None, trade: str = "structures") -> dict:
    """The picture's data: its stations with their questions and answers, the
    chapters they follow, the per-element table of the mix and the totals.

    ``questions`` are what ``specs_questions.asked`` gives; ``words`` the
    sections as the files say them (``specs_review.issued_words(..., marked=True)``);
    ``place_url(row_id, node_id)`` links a paragraph. With ``decided`` given,
    the project's decisions (``chosen``) are the first level, the brief, open
    until the engineer has decided them."""
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
    if decided is not None:
        brief = stations["decide"]
        brief["needed" if not decided else "answered"] = 1
        brief["decisions"] = decisions(chosen, options or [])
        shown_stations.insert(0, brief)
        chapters = [{**DECIDING, "questions": []}] + chapters
    out_chapters = []
    for c in chapters:
        held = [s for s in shown_stations if s["chapter"] == c["slug"]]
        needed, suggested = sum(s["needed"] for s in held), sum(s["suggested"] for s in held)
        out_chapters.append({"slug": c["slug"], "number": c["number"], "name": c["name"], "lead": c["lead"],
                             "stations": [s["id"] for s in held], "needed": needed, "suggested": suggested,
                             "done": not needed and not suggested})
    # The stages open in turn: a chapter opens once every one before it is
    # answered, a suggestion counting once the engineer accepts it. One that is
    # answered stays open to change, wherever it is: a change to the brief
    # reopens only the levels it puts new questions in.
    site = site_of(chosen if chosen is not None else {}, trade)
    for c in out_chapters:
        c["story"] = narrative(c["slug"], site)
    open_stage = next((i for i, c in enumerate(out_chapters) if not c["done"]), len(out_chapters))
    for i, c in enumerate(out_chapters):
        c["stage"] = i
        c["level"] = i + 1
        c["locked"] = i > open_stage and not c["done"]
        for sid in c["stations"]:
            stations[sid]["stage"] = i
            stations[sid]["level"] = i + 1
            stations[sid]["locked"] = c["locked"]
    return {"stations": shown_stations, "chapters": out_chapters, "open_stage": open_stage,
            "site": site,
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
    return {"number": c["number"], "level": c["level"], "name": c["name"], "slug": c["slug"],
            "left": c["needed"] + c["suggested"], "station": first}


# Where a section stands when none of its questions says: by its number, the
# MasterFormat division (or NBS work section) it is in.
BY_NUMBER = [
    (re.compile(r"^0?3\s*01"), "repair"), (re.compile(r"^0?3\s*1"), "formwork"),
    (re.compile(r"^0?3\s*2"), "rebar"), (re.compile(r"^0?3\s*38"), "tendons"),
    (re.compile(r"^0?3\s*[45]"), "precast"), (re.compile(r"^0?3"), "pour"),
    (re.compile(r"^0?5"), "frame"), (re.compile(r"^0?7"), "membrane"),
    (re.compile(r"^0?1\s*4"), "lab"), (re.compile(r"^0?1"), "documents"),
    (re.compile(r"^0?2|^31"), "shoring"), (re.compile(r"^3[45]"), "bridge"),
    (re.compile(r"^E\s*20", re.I), "formwork"), (re.compile(r"^E\s*3[01]", re.I), "rebar"),
    (re.compile(r"^E\s*5", re.I), "precast"), (re.compile(r"^E", re.I), "pour"),
    (re.compile(r"^G", re.I), "frame"), (re.compile(r"^J", re.I), "membrane"),
    (re.compile(r"^[AC]", re.I), "documents"),
]


def section_stations(questions: list[dict]) -> dict[str, str]:
    """Each section's station: where most of its questions stand."""
    counts: dict[str, dict[str, int]] = {}
    for c in specs_questions.story(questions):
        for q in c["questions"]:
            sid = station_of(q, c["slug"])
            for number in q["sections"]:
                counts.setdefault(number, {}).setdefault(sid, 0)
                counts[number][sid] += 1
    return {n: max(c, key=c.get) for n, c in counts.items()}


# The geotechnical library's sections, by number, when no question says.
GEO_BY_NUMBER = [
    (re.compile(r"^02"), "g_investigation"), (re.compile(r"^3108|^316|^D30", re.I), "g_piles"),
    (re.compile(r"^31[12]|^3105|^3131|^3341|^D20", re.I), "g_earthworks"),
    (re.compile(r"^313[24]|^3145"), "g_improvement"),
    (re.compile(r"^313[3-7]|^315|^D4", re.I), "g_retaining"), (re.compile(r"^317|^3305"), "g_tunnels"),
    (re.compile(r"^32|^Q", re.I), "g_pavements"), (re.compile(r"^357"), "g_dams"), (re.compile(r"^35"), "g_marine"),
]


def station_of_section(number: str, known: Mapping[str, str], trade: str = "structures") -> str:
    number = (number or "").strip()
    if number in known:
        return known[number]
    table = GEO_BY_NUMBER if trade == "geotechnical" else BY_NUMBER
    return next((sid for words, sid in table if words.match(number)), "other")


def flags(report: Mapping[str, Any], language: Mapping[str, list], checks: list[tuple],
          kinds: list[tuple], questions: list[dict], advice: tuple | set = ()) -> dict:
    """The check's open findings placed on the works: at the station of the
    section each concerns, by station, with the group it is under, its words
    and its place on the check page (``#item-<key>``, ``#language``). Groups
    that are only ``advice`` are left off, and a language change is counted
    once, at the first place it is in, as the check counts them."""
    known = section_stations(questions)
    trade = next((q.get("trade") for q in questions if q.get("trade")), "structures")
    # A clause against an answer stands where the question is asked.
    asked_at = {q["key"]: station_of(q, c["slug"])
                for c in specs_questions.story(questions) for q in c["questions"]}
    out: dict[str, list[dict]] = {}
    titles = {k: t for k, t, _a in checks}
    for key, _title, _about in checks:
        if key in advice:
            continue
        for item in report.get(key) or []:
            if item.get("settled") or item.get("done"):
                continue
            c = item.get("conflict") or {}
            question = c.get("key") or next((a["key"] for a in c.get("answers") or []), "")
            sid = asked_at.get(question) or station_of_section(item.get("section") or "", known, trade)
            out.setdefault(sid, []).append({
                "group": titles[key], "kind": key, "severity": item.get("severity") or "",
                "text": item.get("message") or "", "section": item.get("section") or "",
                "url": "#item-" + (item.get("key") or "")})
    names = {k: t for k, t, *_rest in kinds}
    for kind, found in (language or {}).items():
        for g in found:
            if g["places"]:
                sid = station_of_section(g["places"][0].get("section") or "", known, trade)
                out.setdefault(sid, []).append({
                    "group": "Language: " + names.get(kind, kind), "kind": "language", "severity": "",
                    "text": (f"{g['old']} → {g['new']}: " if g["old"] and g["new"] else
                             f"{g['old']}: " if g["old"] else "") + (g["message"] or ""),
                    "section": ", ".join(sorted({p.get("section") or "" for p in g["places"]})),
                    "url": "#language"})
    return {"stations": out, "total": sum(len(v) for v in out.values()),
            "names": {sid: name for sid, _c, name, _w in STATIONS}}
