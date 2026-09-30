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
            # SI units.
            for at, old, new, why in unit_findings(text):
                add("units", at, old, new, why)
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


# --- SI units ----------------------------------------------------------------------------

NUM = r"(?:\d+\s*-\s*\d+/\d+|\d+/\d+|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
SPAN = NUM + r"(?:\s*(?:to|-|–)\s*" + NUM + r")?"
# imperial unit, the SI one it becomes, what to multiply by, how to round
IMPERIAL: list[tuple[str, str, float, str]] = [
    (r"(?:°\s*F|deg(?:rees?)?\.?\s*F)\b", "°C", 0.0, "temperature"),
    (r"(?:lbs?\.?\s*/\s*cu\.?\s*ft\.?|pcf\b)", "kg/m3", 16.018, "sig"),
    (r"oz\.?\s*/\s*sq\.?\s*ft\.?", "g/m2", 305.15, "sig"),
    (r"(?:sq\.?\s*ft\.?|square\s+(?:feet|foot))", "m2", 0.092903, "sig"),
    (r"(?:sq\.?\s*yd\.?|square\s+yards?)", "m2", 0.836127, "sig"),
    (r"(?:cu\.?\s*yd\.?|cubic\s+yards?)", "m3", 0.764555, "sig"),
    (r"(?:cu\.?\s*ft\.?|cubic\s+(?:feet|foot))", "m3", 0.0283168, "sig"),
    (r"ksi\b", "MPa", 6.894757, "MPa"),
    (r"psi\b", "MPa", 0.006894757, "MPa"),
    (r"kips?\b", "kN", 4.448222, "sig"),
    (r"lbf\b", "N", 4.448222, "sig"),
    (r"(?:lbs?\.?|pounds?)(?![\w/])", "kg", 0.453592, "sig"),
    (r"(?:inch(?:es)?\b|in\.(?=[\s,;)]|$)|\"(?![A-Za-z0-9]))", "mm", 25.4, "mm"),
    (r"(?:feet|foot|ft\.?)(?![\w/])", "m", 0.3048, "m"),
    (r"(?:yards?|yd\.?)(?![\w/])", "m", 0.9144, "m"),
    (r"gal(?:lons?)?\.?(?![\w/])", "L", 3.785412, "sig"),
    (r"mph\b", "km/h", 1.609344, "sig"),
    (r"mils?\b", "µm", 25.4, "um"),
]
SI_UNIT = (r"(?:mm|m|MPa|N/mm2|N/mm²|°\s*C|deg(?:rees?)?\.?\s*C|kg/m3|kg/m³|kg|kN|N|L|µm|microns?|m2|m²|"
           r"m3|m³|g/m2|g/m²|km/h)\b")
IMPERIAL_ANY = "|".join(f"(?:{u})" for u, *_ in IMPERIAL)
SI_QTY = r"(?P<si>" + SPAN + r"\s*-?\s*" + SI_UNIT + r")"
IMP_QTY = r"(?P<imp>" + SPAN + r"\s*-?\s*(?:" + IMPERIAL_ANY + r"))"
SI_THEN_IMPERIAL = re.compile(SI_QTY + r"\s*\(\s*" + IMP_QTY + r"\s*\)")
IMPERIAL_THEN_SI = re.compile(IMP_QTY + r"\s*\(\s*" + SI_QTY + r"\s*\)")
IMPERIAL_ALONE = re.compile(r"(?<![\w.])" + IMP_QTY)


def _number(text: str) -> float:
    text = text.replace(",", "").strip()
    whole = re.fullmatch(r"(\d+)\s*-\s*(\d+)/(\d+)", text)
    if whole:
        return int(whole.group(1)) + int(whole.group(2)) / int(whole.group(3))
    part = re.fullmatch(r"(\d+)/(\d+)", text)
    if part:
        return int(part.group(1)) / int(part.group(2))
    return float(text)


def _nice(value: float, rounding: str) -> str:
    if rounding == "temperature" or rounding == "int":
        out = round(value)
    elif rounding == "mm":
        out = round(value) if value < 20 else 5 * round(value / 5)
    elif rounding == "um":
        out = 5 * round(value / 5)
    elif rounding == "MPa":
        out = round(value, 1) if value < 100 else round(value)
    elif rounding == "m":
        out = round(value, 2)
    else:
        digits = 3 - len(str(int(abs(value)))) if value >= 1 else 3
        out = round(value, digits)
    text = f"{out:.10g}"
    return text


def _imperial(qty: str) -> tuple[list[float], str, float, str] | None:
    """The numbers of an imperial quantity, and how each becomes SI."""
    for unit, si, factor, rounding in IMPERIAL:
        m = re.fullmatch(r"(" + SPAN + r")\s*-?\s*(?:" + unit + r")", qty.strip(), re.I)
        if m:
            numbers = re.findall(NUM, m.group(1))
            try:
                return [_number(n) for n in numbers], si, factor, rounding
            except (ValueError, ZeroDivisionError):
                return None
    return None


def _si_values(qty: str) -> tuple[list[float], str, str] | None:
    found = _imperial(qty)
    if not found:
        return None
    numbers, si, factor, rounding = found
    if rounding == "temperature":
        return [(n - 32) * 5 / 9 for n in numbers], si, rounding
    return [n * factor for n in numbers], si, rounding


def _to_si(qty: str) -> str | None:
    found = _si_values(qty)
    if not found:
        return None
    values, si, rounding = found
    return " to ".join(_nice(v, rounding) for v in values) + f" {si}"


def _si_numbers(qty: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", qty)]


def unit_findings(text: str) -> list[tuple[int, str, str, str]]:
    """Imperial units, each with its SI suggestion: ``(at, old, new, why)``."""
    out: list[tuple[int, str, str, str]] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return not any(x < b and a < y for x, y in taken)

    for rule, keep in ((SI_THEN_IMPERIAL, "si"), (IMPERIAL_THEN_SI, "si")):
        for m in rule.finditer(text):
            if not free(*m.span()):
                continue
            taken.append(m.span())
            si, imp = m.group("si"), m.group("imp")
            converted = _to_si(imp)
            why = "SI only: the imperial figure goes"
            if converted:
                a, b = _si_numbers(si), _si_values(imp)[0]
                found = _imperial(imp)
                if a and b and len(a) == len(b) and not all(
                        abs(x - y) <= max(1.5, 0.03 * abs(x)) for x, y in zip(a, b)):
                    as_difference = found and found[3] == "temperature" and all(
                        abs(x - n * 5 / 9) <= 1.5 for x, n in zip(a, found[0]))
                    if not as_difference:
                        why = (f"the two figures disagree: {imp.strip()} is {converted}, not "
                               f"{si.strip()}; check which is meant before accepting")
            out.append((m.start(), m.group(0), si.strip(), why))
    for m in IMPERIAL_ALONE.finditer(text):
        if not free(*m.span()) or re.search(
                r"\b(?:Section|Article|Paragraph|Clause|Part|Table|Figure|Grade|Type|Class)\s*$",
                text[max(0, m.start() - 14):m.start()], re.I):
            continue
        converted = _to_si(m.group("imp"))
        if converted:
            out.append((m.start(), m.group(0), converted,
                        "SI only; the figure is converted and rounded, so check it"))
    return sorted(out)
