"""The language of a specification: one English, correct grammar, the
office's own words — as suggestions, never changes.

Nothing here edits a section. Each finding says where it is, what the words
are, and what they could be; the engineer accepts it, types something else,
or leaves it. That is also how a project's scope reaches its wording: a
project with no buildings is offered "structure" wherever "building" is used.

Everything is rules and word lists — the text of a project never leaves the
server to be checked.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from . import specs

# --- UK and US spelling ------------------------------------------------------------

# UK spelling, US spelling. Each form is listed; case is kept when replacing.
PAIRS: list[tuple[str, str]] = [
    ("colour", "color"), ("colours", "colors"), ("coloured", "colored"), ("colouring", "coloring"),
    ("behaviour", "behavior"), ("labour", "labor"), ("favourable", "favorable"),
    ("harbour", "harbor"), ("harbours", "harbors"), ("neighbouring", "neighboring"),
    ("vapour", "vapor"), ("odour", "odor"), ("rigour", "rigor"), ("honour", "honor"),
    ("mould", "mold"), ("moulds", "molds"), ("moulded", "molded"), ("moulding", "molding"),
    ("centre", "center"), ("centres", "centers"), ("centred", "centered"), ("centreline", "centerline"),
    ("centrelines", "centerlines"), ("metre", "meter"), ("metres", "meters"),
    ("millimetre", "millimeter"), ("millimetres", "millimeters"), ("centimetre", "centimeter"),
    ("centimetres", "centimeters"), ("kilometre", "kilometer"), ("kilometres", "kilometers"),
    ("litre", "liter"), ("litres", "liters"), ("fibre", "fiber"), ("fibres", "fibers"),
    ("aluminium", "aluminum"), ("grey", "gray"), ("catalogue", "catalog"), ("catalogues", "catalogs"),
    ("defence", "defense"), ("licence", "license"), ("fulfil", "fulfill"), ("fulfilment", "fulfillment"),
    ("instalment", "installment"), ("ageing", "aging"), ("manoeuvre", "maneuver"),
    ("per cent", "percent"), ("programme", "program"), ("programmes", "programs"),
    ("storey", "story"), ("storeys", "stories"), ("tonne", "ton"), ("tonnes", "tons"),
    ("modelling", "modeling"), ("labelled", "labeled"), ("labelling", "labeling"),
    ("levelled", "leveled"), ("levelling", "leveling"), ("travelled", "traveled"),
    ("cancelled", "canceled"), ("signalling", "signaling"), ("channelled", "channeled"),
    ("tunnelling", "tunneling"), ("jewellery", "jewelry"), ("sulphate", "sulfate"),
    ("sulphates", "sulfates"), ("sulphur", "sulfur"), ("sulphide", "sulfide"),
    ("analyse", "analyze"), ("analysed", "analyzed"), ("analysing", "analyzing"),
    ("paralyse", "paralyze"), ("catalyse", "catalyze"),
]
# Words a US text writes "-ize" and a UK one "-ise", unless it follows Oxford.
IZE = ["galvan", "organ", "minim", "maxim", "recogn", "special", "standard", "util", "final",
       "author", "emphas", "priorit", "optim", "stabil", "neutral", "harmon", "summar", "categor",
       "character", "synchron", "visual", "custom", "steril", "pulver", "crystall", "oxid",
       "polymer", "energ", "real", "apolog", "critic", "central", "normal", "equal", "general",
       "legal", "local", "mobil", "modern", "penal", "capital", "memor"]
IZE_ENDINGS = [("ise", "ize"), ("ised", "ized"), ("ises", "izes"), ("ising", "izing"),
               ("isation", "ization"), ("isations", "izations"), ("iser", "izer"), ("isers", "izers")]
# "meter" is also an instrument (a cover meter), so only a length is changed.
LENGTH_METER = re.compile(r"(?<=\d )meters?\b|(?<=\d)meters?\b|\b(?:per|square|cubic|linear) meters?\b",
                          re.I)


def _ize_pairs() -> list[tuple[str, str]]:
    out = []
    for stem in IZE:
        for uk, us in IZE_ENDINGS:
            out.append((stem + uk, stem + us))
    return out


VARIANTS = ("UK", "UK with -ize", "US")


def _spelling_table(english: str) -> dict[str, str]:
    """Wrong form → right form for the project's English."""
    english = (english or "").strip()
    table: dict[str, str] = {}
    if english == "US":
        for uk, us in PAIRS + _ize_pairs():
            table[uk] = us
        for us in ("meter", "meters"):
            table.pop(us, None)
    elif english in ("UK", "UK with -ize"):
        for uk, us in PAIRS:
            if us in ("meter", "meters", "story", "stories", "ton", "tons", "program", "programs",
                      "license"):
                continue                        # also right in UK English, in another sense
            table[us] = uk
        if english == "UK":
            for uk, us in _ize_pairs():
                table[us] = uk
        else:
            for uk, us in _ize_pairs():
                table[uk] = us
    return table


# --- spelling mistakes ------------------------------------------------------------------

MISSPELT = {
    "accomodate": "accommodate", "accomodation": "accommodation", "acheive": "achieve",
    "adress": "address", "aggresive": "aggressive", "agregate": "aggregate", "aggragate": "aggregate",
    "aggegate": "aggregate", "apparant": "apparent", "appropiate": "appropriate",
    "assesment": "assessment", "begining": "beginning", "beleive": "believe", "bouyancy": "buoyancy",
    "commited": "committed", "committment": "commitment", "compatable": "compatible",
    "consistant": "consistent", "continous": "continuous", "critera": "criteria",
    "definately": "definitely", "embedement": "embedment", "enviroment": "environment",
    "enviromental": "environmental", "equiptment": "equipment", "existance": "existence",
    "gaurantee": "guarantee", "guage": "gauge", "heigth": "height", "hieght": "height",
    "immediatly": "immediately", "independant": "independent", "installtion": "installation",
    "lenght": "length", "maintainance": "maintenance", "maintenence": "maintenance",
    "manufacturor": "manufacturer", "maximun": "maximum", "mesurement": "measurement",
    "minumum": "minimum", "neccessary": "necessary", "necesary": "necessary", "necessery": "necessary",
    "occassion": "occasion", "occured": "occurred", "occurence": "occurrence", "occuring": "occurring",
    "perfomance": "performance", "permanant": "permanent", "posession": "possession",
    "prefered": "preferred", "proceedure": "procedure", "recieve": "receive", "recieved": "received",
    "reccomend": "recommend", "recomend": "recommend", "recommendded": "recommended",
    "refered": "referred", "reinforcment": "reinforcement", "reinforcemnt": "reinforcement",
    "relevent": "relevant", "requirment": "requirement", "requirments": "requirements",
    "resistence": "resistance", "responsability": "responsibility", "seperate": "separate",
    "seperately": "separately", "strenght": "strength", "strengh": "strength",
    "submital": "submittal", "submitals": "submittals", "succesful": "successful",
    "sufficent": "sufficient", "supercede": "supersede", "temperture": "temperature",
    "tempreature": "temperature", "thier": "their", "tollerance": "tolerance",
    "tollerances": "tolerances", "transfered": "transferred", "untill": "until",
    "visable": "visible", "weigth": "weight", "wich": "which", "withold": "withhold",
    "accross": "across", "alot": "a lot", "concious": "conscious", "dimention": "dimension",
    "dimentions": "dimensions", "excavtion": "excavation", "fabricaton": "fabrication",
    "foundaton": "foundation", "horizonal": "horizontal", "verticle": "vertical",
    "substract": "subtract", "througout": "throughout", "unforseen": "unforeseen",
    "wheather": "weather", "specifiction": "specification", "speciication": "specification",
}

# --- grammar ------------------------------------------------------------------------

SHALL_VERB = {"complies": "comply", "conforms": "conform", "meets": "meet", "provides": "provide",
              "includes": "include", "requires": "require", "has": "have", "is": "be", "are": "be",
              "does": "do", "applies": "apply", "consists": "consist", "remains": "remain"}
PARTICIPLE = {"provide": "provided", "install": "installed", "submit": "submitted", "place": "placed",
              "test": "tested", "use": "used", "apply": "applied", "remove": "removed",
              "repair": "repaired", "protect": "protected", "maintain": "maintained",
              "construct": "constructed", "design": "designed", "fabricate": "fabricated",
              "supply": "supplied", "deliver": "delivered", "store": "stored", "clean": "cleaned",
              "cure": "cured", "finish": "finished", "approve": "approved", "replace": "replaced",
              "reject": "rejected", "mark": "marked", "prepare": "prepared", "inspect": "inspected",
              "weld": "welded", "paint": "painted", "coat": "coated", "seal": "sealed", "fix": "fixed",
              "support": "supported", "carry": "carried", "make": "made", "take": "taken",
              "give": "given", "do": "done", "keep": "kept", "hold": "held", "cast": "cast"}
AN_BEFORE = re.compile(r"\b(a|an)\s+([A-Za-z][\w-]*)")
A_BEFORE_VOWEL_OK = ("uni", "use", "usa", "usu", "uti", "ure", "eu", "one", "once", "ubi", "uk")
AN_BEFORE_H = ("hour", "honest", "honour", "honor", "heir")
LETTER_AN = set("AEFHILMNORSX")      # letters said with a vowel sound: "an M20 bar", "an HDPE pipe"
ABBREVIATIONS = ("e.g", "i.e", "etc", "approx", "no", "min", "max", "nos", "incl", "ref", "fig", "sq", "cu",
                 "nr", "hr", "hrs", "kg", "mm", "dim", "temp", "reqd", "std", "spec", "specs",
                 "cl", "vol", "viz", "al", "vs", "dia")


def _article(article: str, word: str) -> str | None:
    """The right article before a word, where it can be told."""
    acronym = word[0].isupper() and (len(word) == 1 or word[:2].isupper() or
                                     bool(re.match(r"[A-Z][\d-]", word)))
    if acronym:
        wanted = "an" if word[0] in LETTER_AN else "a"
    else:
        low = word.lower()
        if low.startswith(AN_BEFORE_H):
            wanted = "an"
        elif low[0] in "aeiou":
            wanted = "a" if low.startswith(A_BEFORE_VOWEL_OK) else "an"
        else:
            wanted = "a"
    if wanted == article.lower():
        return None
    return wanted.capitalize() if article[0].isupper() else wanted


# --- the office's words, and the project's scope ---------------------------------------

def _case_like(model: str, word: str) -> str:
    if model.isupper() and len(model) > 1:
        return word.upper()
    if model[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    """Titles in quotes: names of documents, never reworded."""
    return [m.span() for m in re.finditer(r"[\"“][^\"“”]{2,200}[\"”]", text)]


def _phrase(find: str) -> re.Pattern:
    words = [re.escape(w) for w in find.split()]
    return re.compile(r"(?<![\w-])" + r"\s+".join(words) + r"(?![\w-])", re.I)


def findings(sections: Sequence[Mapping[str, Any]], chosen: Mapping[str, str], english: str,
             wording: Iterable[Mapping[str, str]] = (), ignored: Iterable[str] = ()) -> list[dict]:
    """Every suggestion for the language of the paragraphs a project issues.

    Each is ``{section, row_id, node_id, path, kind, message, old, new, at,
    text}``: ``old`` is the words as they stand at ``at`` in the paragraph's
    text, ``new`` what they could be (blank where only the engineer can say).
    """
    ignored = {w.lower() for w in ignored}
    spelling = _spelling_table(english)
    rules = []
    for row in wording:
        find = (row.get("find") or "").strip()
        if not find:
            continue
        if (row.get("when") or "").strip() and not specs.applies(row["when"], chosen):
            continue
        unless = [u.strip().lower() for u in (row.get("unless_next") or "").split(",") if u.strip()]
        rules.append((_phrase(find), (row.get("replace") or "").strip(), row.get("note") or "",
                      (row.get("when") or "").strip(), unless))

    out: list[dict] = []
    for s in sections:
        for n in specs.number(s["nodes"], chosen):
            if not n["included"] or n["level"] in (specs.NOTE,):
                continue
            text = n["text"]
            quoted = _quoted_spans(text)
            # Words inside a standard's citation, a variable or a reference are left alone.
            shielded = quoted + [m.span() for m in re.finditer(
                r"\{\{[^}]*\}\}|\{ref:[^}]*\}|\{if[^}]*\}|https?://\S+", text)]

            def free(a: int, b: int) -> bool:
                return not any(x < b and a < y for x, y in shielded)

            def add(kind: str, at: int, old: str, new: str, message: str) -> None:
                if old.lower() in ignored or not free(at, at + len(old)):
                    return
                out.append({"section": s["number"], "row_id": s.get("id"), "node_id": n["id"],
                            "path": n["path"], "kind": kind, "message": message, "old": old,
                            "new": new, "at": at, "text": _around(text, at, len(old))})

            # One English.
            if spelling:
                for m in re.finditer(r"[A-Za-z]+(?: cent\b)?", text):
                    word = m.group(0)
                    right = spelling.get(word.lower())
                    if right and right.lower() != word.lower():
                        add("english", m.start(), word, _case_like(word, right),
                            f"{english} English spells it \"{right}\"")
                if english in ("UK", "UK with -ize"):
                    for m in LENGTH_METER.finditer(text):
                        word = m.group(0)
                        add("english", m.start(), word, word.replace("meter", "metre").replace(
                            "Meter", "Metre"), f"{english} English spells a length \"metre\"")
            # Spelling mistakes.
            for m in re.finditer(r"[A-Za-z]+", text):
                right = MISSPELT.get(m.group(0).lower())
                if right:
                    add("spelling", m.start(), m.group(0), _case_like(m.group(0), right),
                        f"spelt \"{right}\"")
            # Grammar.
            for m in re.finditer(r"\b(\w+)(\s+)(\1)\b", text, re.I):
                if not m.group(1).isdigit() and m.group(1).lower() not in ("that", "had"):
                    add("grammar", m.start(), m.group(0), m.group(1), "the same word twice")
            for m in AN_BEFORE.finditer(text):
                wanted = _article(m.group(1), m.group(2))
                if wanted:
                    add("grammar", m.start(), m.group(1), wanted,
                        f"\"{wanted.lower()} {m.group(2)}\", not \"{m.group(1).lower()} {m.group(2)}\"")
            for m in re.finditer(r"\bshall\s+(not\s+)?(%s)\b" % "|".join(SHALL_VERB), text, re.I):
                verb = m.group(2)
                add("grammar", m.start(2), verb, _case_like(verb, SHALL_VERB[verb.lower()]),
                    f"\"shall {SHALL_VERB[verb.lower()]}\", not \"shall {verb.lower()}\"")
            for m in re.finditer(r"\b(shall|must|will|to)\s+(not\s+)?be\s+(%s)\b" % "|".join(PARTICIPLE),
                                 text, re.I):
                verb = m.group(3)
                right = PARTICIPLE[verb.lower()]
                if right != verb.lower():
                    add("grammar", m.start(3), verb, _case_like(verb, right),
                        f"\"be {right}\", not \"be {verb.lower()}\"")
            for m in re.finditer(r"(?<=\w)\s+([,;:])(?!\d)", text):
                add("grammar", m.start(), m.group(0), m.group(1), "a space before the punctuation")
            for m in re.finditer(r"(?<=[a-z]),(?=[A-Za-z])", text):
                add("grammar", m.start(), ",", ", ", "no space after the comma")
            for m in re.finditer(r"\bit's\b", text, re.I):
                add("grammar", m.start(), m.group(0), _case_like(m.group(0), "its"),
                    "\"its\" (belonging to it), unless \"it is\" is meant")
            for m in re.finditer(r"\b([A-Za-z]+)\.\s+([a-z])(?=[a-z])", text):
                if m.group(1).lower() in ABBREVIATIONS or len(m.group(1)) == 1:
                    continue
                add("grammar", m.start(2), m.group(2), m.group(2).upper(),
                    "a sentence starts with a capital letter")
            if n["level"] != specs.TABLE and text.count("(") != text.count(")"):
                add("grammar", 0, "", "", "the brackets do not pair up")
            # The office's words, and the project's scope.
            for rule, replace, note, when, unless in rules:
                for m in rule.finditer(text):
                    after = text[m.end():m.end() + 30].strip().split(" ")[0].lower().strip(",.;:")
                    if after in unless:
                        continue
                    new = _case_like(m.group(0), replace) if replace else ""
                    add("scope" if when else "wording", m.start(), m.group(0), new,
                        note or (f"the office writes \"{replace}\"" if replace else "reword"))
    return out


def _around(text: str, at: int, length: int, room: int = 60) -> dict:
    start, end = max(0, at - room), min(len(text), at + length + room)
    return {"before": ("…" if start else "") + text[start:at], "words": text[at:at + length],
            "after": text[at + length:end] + ("…" if end < len(text) else "")}


def accept(text: str, old: str, new: str, at: int | None = None) -> tuple[str, int]:
    """One suggestion taken: the words at ``at`` if they still read ``old``,
    else the first place they do."""
    if at is not None and 0 <= at and text[at:at + len(old)] == old:
        return text[:at] + new + text[at + len(old):], 1
    found = text.find(old)
    if found < 0 or not old:
        return text, 0
    return text[:found] + new + text[found + len(old):], 1


def accept_everywhere(text: str, old: str, new: str) -> tuple[str, int]:
    """The same words changed wherever they stand whole, keeping their case."""
    rule = _phrase(old)
    count = 0

    def one(m: re.Match) -> str:
        nonlocal count
        count += 1
        return _case_like(m.group(0), new) if old.lower() != new.lower() else new

    shielded = _quoted_spans(text)
    out, last = [], 0
    for m in rule.finditer(text):
        if any(x < m.end() and m.start() < y for x, y in shielded):
            continue
        out.append(text[last:m.start()])
        out.append(one(m))
        last = m.end()
    out.append(text[last:])
    return "".join(out), count
