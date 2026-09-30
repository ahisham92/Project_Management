"""Checking a specification: references, standards, discrepancies, repeats.

A specification issued across forty sections is only as good as the places
they meet. This is what reads across them:

**Cross-references that keep themselves right.** Text refers to another
section as ``{ref:033000}``, to an article by its title as ``{ref:CURING}`` or
``{ref:033000/CURING}``, and to any paragraph by its id as ``{ref:#1a2b3c4d}``.
They are written out when the section is shown or issued — ``Section 033000
"Cast-in-Place Concrete"``, ``Article 3.7``, ``Paragraph 2.4.B`` — from the
numbers as they stand for this project, so a paragraph added, dropped or
switched off moves every reference to it, and a reference to a section that
was taken out is caught rather than issued.

**One basis of standards.** Every standard cited is recognised. The project
says BS EN, ACI/ASTM or both, and the equivalents table puts every citation on
that basis when the section is shown and issued. Citations with no equivalent
recorded are reported, and so are ones the table knows to be withdrawn.

**Discrepancies and repeats.** The same property given different values in
different places, a section cited under the wrong title or not issued at all,
a standard cited in two editions; and the values and paragraphs repeated so
often that they should be one variable or one paragraph.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from . import specs

# --- standards ---------------------------------------------------------------------

STANDARD = re.compile(
    r"""\b(?P<body>
        (?P<org>BS\s+EN\s+ISO/IEC|ISO/IEC|BS\s+EN\s+ISO|BS\s+EN|BS\s+ISO|EN\s+ISO|BS|EN|ISO|ASTM|ACI|AASHTO|AWS|AISC
            |CRSI|PCI|SSPC|ASCE|NF\s+EN|DIN\s+EN|DIN)
        \s*(?:SP-|MNL-)?[A-Z]{0,2}\s?\d+(?:\.\d+)*(?:-\d+)*[A-Z]?
        (?:/[A-Z]{0,2}\s?\d+(?:\.\d+)*M?(?:-\d\d(?!\d))?)?
    )(?P<year>\s*(?::\s*|-)(?:19|20)\d\d)?\b""", re.X)

US_ORGS = {"ASTM", "ACI", "AASHTO", "AWS", "AISC", "CRSI", "PCI", "SSPC", "ASCE"}


def std_key(ref: str) -> str:
    """One way of writing a standard, whatever way it was typed.

    ``ASTM C 150/C150M-20`` and ``ASTM C150`` are one; so are ``BS EN ISO
    1461`` and ``EN ISO 1461``. The edition and the metric twin are dropped.
    """
    match = STANDARD.search(ref or "")
    body = match.group("body") if match else (ref or "")
    body = re.sub(r"(\d[\w.\-]*)\s*/.*$", r"\1", body)      # the metric twin, not ISO/IEC
    key = re.sub(r"\s+", "", body.upper())
    key = re.sub(r"^BS(?=EN|ISO)", "", key)
    key = re.sub(r"^(NF|DIN)(?=EN)", "", key)
    if re.match(r"^(ASTM|ACI|AWS|AASHTO)", key):
        key = re.sub(r"-\d\d$", "", key)                    # ACI 318-19: the 2019 edition
        key = re.sub(r"(?<=\d)M$", "", key)
    return key


def std_year(match: re.Match) -> int | None:
    year = match.group("year")
    digits = re.search(r"(19|20)\d\d", year or "")
    if digits:
        return int(digits.group(0))
    short = re.search(r"-(\d\d)$", match.group("body"))
    if short and family(match.group(0)) == "us":
        two = int(short.group(1))
        return 2000 + two if two < 50 else 1900 + two
    return None


def family(ref: str) -> str:
    """``us`` for ASTM, ACI and their like; ``bs`` for BS, EN and ISO."""
    match = STANDARD.search(ref or "")
    org = re.sub(r"\s+", " ", match.group("org")).upper() if match else ""
    return "us" if org in US_ORGS else "bs"


def basis_of(value: str) -> str:
    """The project's standards basis as ``bs``, ``us`` or ``both``."""
    value = (value or "").lower()
    if "both" in value or ("|" in value and "bs" in value and ("astm" in value or "aci" in value)):
        return "both"
    if "astm" in value or "aci" in value:
        return "us"
    if "bs" in value or "en" in value:
        return "bs"
    return ""


class Standards:
    """The equivalents and the withdrawn standards, looked up by key."""

    def __init__(self, pairs: Iterable[Mapping[str, str]] = (),
                 withdrawn: Iterable[Mapping[str, str]] = ()):
        self.to_bs: dict[str, str] = {}
        self.to_us: dict[str, str] = {}
        self.topic: dict[str, str] = {}
        for pair in pairs:
            bs, us = (pair.get("bs") or "").strip(), (pair.get("us") or "").strip()
            if not bs or not us:
                continue
            for one in us.split(";"):
                if one.strip():
                    self.to_bs.setdefault(std_key(one), bs)
                    self.topic[std_key(one)] = pair.get("topic", "")
            self.to_us.setdefault(std_key(bs), us.split(";")[0].strip())
            self.topic[std_key(bs)] = pair.get("topic", "")
        self.withdrawn: dict[str, list[dict]] = defaultdict(list)
        for row in withdrawn:
            old = (row.get("old") or "").strip()
            if not old:
                continue
            match = STANDARD.search(old)
            self.withdrawn[std_key(old)].append({
                "old": old, "new": (row.get("new") or "").strip(), "note": row.get("note", ""),
                "upto": std_year(match) if match else None})

    def equivalent(self, ref: str) -> str | None:
        key = std_key(ref)
        return self.to_bs.get(key) if family(ref) == "us" else self.to_us.get(key)

    def outdated(self, ref: str, year: int | None) -> dict | None:
        key = std_key(ref)
        base = key.split("-")[0]
        for row in self.withdrawn.get(key, []) + (self.withdrawn.get(base, []) if base != key else []):
            if row["upto"] is None or (year is not None and year <= row["upto"]):
                return row
        return None


def _dedupe(text: str) -> str:
    """"BS EN 197-1 or BS EN 197-1" said once, after a conversion made it twice."""
    changed = True
    while changed:
        changed = False
        found = list(STANDARD.finditer(text))
        for a, b in zip(found, found[1:]):
            gap = text[a.end():b.start()]
            if std_key(a.group(0)) == std_key(b.group(0)) and \
                    re.fullmatch(r"\s*(?:,?\s*(?:or|and)|,|/|\(|;)?\s*", gap, re.I):
                end = b.end()
                if gap.strip() == "(" and text[end:end + 1] == ")":
                    end += 1
                text = text[:a.end()] + text[end:]
                changed = True
                break
    return text


TITLE_AFTER = re.compile(r"\s*,?\s*[\"“][^\"“”]{3,160}[\"”]")


def convert(text: str, basis: str, table: Standards) -> str:
    """The text with every standard it cites put on the project's basis.

    On a single basis, a citation from the other side becomes its equivalent,
    and a pair that has become the same standard twice is said once; the
    title quoted after it, which named the old one, goes with it. On both, a
    citation whose equivalent is not already beside it gains it, after its
    title if it has one.
    """
    if not basis or not text or not STANDARD.search(text):
        return text
    out: list[str] = []
    last = 0
    present = {std_key(m.group(0)) for m in STANDARD.finditer(text)}
    for m in STANDARD.finditer(text):
        if m.start() < last:
            continue
        ref = m.group(0)
        side = family(ref)
        other = table.equivalent(ref)
        end = m.end()
        replacement = ref
        title = TITLE_AFTER.match(text, end)
        if other:
            if (basis == "bs" and side == "us") or (basis == "us" and side == "bs"):
                replacement = other
                if title:
                    end = title.end()
            elif basis == "both" and std_key(other) not in present:
                if title:
                    replacement = ref + title.group(0) + f" or {other}"
                    end = title.end()
                else:
                    replacement = f"{ref} or {other}"
                present.add(std_key(other))
        out.append(text[last:m.start()])
        out.append(replacement)
        last = end
    out.append(text[last:])
    result = "".join(out)
    return _dedupe(result) if basis in ("bs", "us") else result


# --- cross-references ----------------------------------------------------------------

REF = re.compile(r"\{ref:\s*([^}]+?)\s*\}")
SMALL = {"and", "or", "of", "the", "for", "in", "to", "a", "an", "on", "at", "by", "with"}


def title_case(title: str) -> str:
    """"CAST-IN-PLACE CONCRETE" as MasterSpec cites it: "Cast-in-Place Concrete"."""
    words = (title or "").lower().split()
    out = []
    for i, word in enumerate(words):
        parts = word.split("-")
        parts = [p if (j > 0 or i > 0) and p in SMALL else p[:1].upper() + p[1:]
                 for j, p in enumerate(parts)]
        out.append("-".join(parts))
    return " ".join(out)


def index(sections: Sequence[Mapping[str, Any]], chosen: Mapping[str, str]) -> dict:
    """Where everything is, for writing references out.

    ``sections`` each carry ``number``, ``title`` and ``nodes``. For each: its
    articles by title, and every paragraph by id, with the path it is cited by
    and whether this project issues it.
    """
    out: dict[str, dict] = {}
    for s in sections:
        articles: dict[str, dict] = {}
        ids: dict[str, dict] = {}
        for n in specs.number(s["nodes"], chosen):
            ids[n["id"]] = {"path": n["path"], "level": n["level"], "included": n["included"],
                            "text": n["text"]}
            if n["level"] == "ART":
                articles.setdefault(_article_key(n["text"]), ids[n["id"]])
        out[_section_key(s["number"])] = {"number": s["number"], "title": s["title"],
                                          "articles": articles, "ids": ids}
    return out


def _section_key(number: str) -> str:
    """033000 and 33000 are one section: a leading nought is often dropped."""
    key = (number or "").strip().upper()
    return key.lstrip("0") or key if key.isdigit() else key


def _article_key(title: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (title or "").upper()).strip()


SECTION_NUMBER = re.compile(r"\d{5,6}|[A-Z]\d{1,3}", re.I)


def lookup(target: str, here: str, where: Mapping[str, dict]) -> dict:
    """What a ``{ref:...}`` points at, or what is wrong with it."""
    target = target.strip()
    if target.startswith("#"):
        ident = target[1:]
        for number, s in where.items():
            if ident in s["ids"]:
                hit = s["ids"][ident]
                return {"kind": "paragraph" if hit["level"] not in ("ART", "PRT") else
                        ("article" if hit["level"] == "ART" else "part"),
                        "section": s, "hit": hit, "here": number == _section_key(here)}
        return {"kind": "missing", "problem": "points at a paragraph that is no longer there"}
    number, _, article = target.partition("/")
    if not article and _section_key(number) not in where and not SECTION_NUMBER.fullmatch(number.strip()):
        number, article = here, target
    section = where.get(_section_key(number))
    if section is None:
        return {"kind": "no-section", "number": number.strip(),
                "problem": f"Section {number.strip()} is not in this specification"}
    if not article:
        return {"kind": "section", "section": section, "here": _section_key(number) == _section_key(here)}
    hit = section["articles"].get(_article_key(article))
    if hit is None:
        return {"kind": "missing", "section": section,
                "problem": f"there is no article \"{article.strip()}\" in Section {section['number']}"}
    return {"kind": "article", "section": section, "hit": hit,
            "here": _section_key(number) == _section_key(here)}


def cite(found: Mapping[str, Any]) -> str:
    """How a reference reads in the issued text."""
    kind = found["kind"]
    if kind == "no-section":
        return f"Section {found['number']}"
    if kind == "missing":
        return "[reference not found]"
    section = found["section"]
    named = f"Section {section['number']} \"{title_case(section['title'])}\""
    if kind == "section":
        return named
    hit = found["hit"]
    if not hit["included"]:
        what = "[reference to a paragraph not issued]"
        return what
    word = {"article": "Article", "part": "Part"}.get(kind, "Paragraph")
    mine = f"{word} {hit['path']}"
    return mine if found.get("here") else f"{mine} of {named}"


def render(text: str, here: str, where: Mapping[str, dict]) -> str:
    return REF.sub(lambda m: cite(lookup(m.group(1), here, where)), text or "")


class Reader:
    """A set of sections read whole: what turns each paragraph's text as kept
    into its text as issued."""

    def __init__(self, sections: Sequence[Mapping[str, Any]], chosen: Mapping[str, str],
                 table: "Standards | None" = None, basis_key: str = "standards"):
        self.where = index(sections, chosen)
        self.basis = basis_of(chosen.get(basis_key, "")) if table is not None else ""
        self.table = table

    def ref(self, target: str, here: str) -> tuple[str, str]:
        """A reference as it reads, and what is wrong with it, if anything."""
        found = lookup(target, here, self.where)
        problem = found.get("problem", "")
        if not problem and found["kind"] not in ("section",) and not found["hit"]["included"]:
            problem = "points at a paragraph this project leaves out"
        return cite(found), problem

    def standards(self, text: str) -> str:
        return convert(text, self.basis, self.table) if self.basis and self.table else text

    def issued(self, here: str):
        def resolve(text: str) -> str:
            return self.standards(render(text, here, self.where))
        return resolve


# Typed-in references a section carries from before they could be live.
TYPED_SECTION = re.compile(
    r"\bSection\s+(?P<number>\d{6}|\d{5}|[A-Z]\d{2})"
    r"(?:\s*[-–,]?\s*[\"“”'](?P<title>[^\"“”']{3,80})[\"“”'],?)?", re.I)
TYPED_ARTICLE = re.compile(
    r"\b(?:Article|article|Section|section|clause|Clause)\s+(?P<path>\d\.\d{1,2})(?![.\d])")
TYPED_PARAGRAPH = re.compile(r"\b(?:Paragraph|paragraph)\s+(?P<path>\d\.\d{1,2}\.[A-Z](?:\.\d{1,2})?)\b")


NAMED_AFTER = "\x00"          # marks a reference just made, until its typed title is dropped


def link_typed(text: str, here: str, where: Mapping[str, dict]) -> tuple[str, int]:
    """Typed references made live where what they name can be found.

    ``Section 033000 "Cast In Place Concrete"`` becomes ``{ref:033000}``;
    ``section 2.4 above`` becomes ``{ref:PROTECTIVE PAINT} above``. A
    reference to something that is not here is left as it was typed.
    """
    count = 0
    mine = where.get(_section_key(here))

    def section(m: re.Match) -> str:
        nonlocal count
        if _section_key(m.group("number")) not in where or _section_key(m.group("number")) == _section_key(here):
            return m.group(0)
        count += 1
        return "{ref:%s}" % m.group("number") + NAMED_AFTER

    def untitled(text: str) -> str:
        """The section's title typed after a reference goes: the reference
        writes it out itself."""
        out, last = [], 0
        for m in re.finditer(r"\{ref:([^}#/]+)\}" + re.escape(NAMED_AFTER), text):
            out.append(text[last:m.end() - len(NAMED_AFTER)])
            last = m.end()
            target = where.get(_section_key(m.group(1)))
            tail = re.match(r"\s*(?:[-–]\s*|,\s*)?([\"“(]?)", text[last:])
            start = last + tail.end()
            title = target["title"] if target else ""
            if title and _article_key(text[start:start + len(title)]) == _article_key(title):
                end = start + len(title)
                if tail.group(1) and text[end:end + 1] in "\"”)":
                    end += 1
                last = end
        out.append(text[last:])
        return "".join(out)

    def article(m: re.Match) -> str:
        nonlocal count
        if mine is None:
            return m.group(0)
        for title, hit in mine["articles"].items():
            if hit["path"] == m.group("path"):
                count += 1
                return "{ref:%s}" % title
        return m.group(0)

    def paragraph(m: re.Match) -> str:
        nonlocal count
        if mine is None:
            return m.group(0)
        for ident, hit in mine["ids"].items():
            if hit["path"] == m.group("path"):
                count += 1
                return "{ref:#%s}" % ident
        return m.group(0)

    text = untitled(TYPED_SECTION.sub(section, text or ""))
    text = TYPED_PARAGRAPH.sub(paragraph, text)
    text = TYPED_ARTICLE.sub(article, text)
    return text, count


# --- the checks ------------------------------------------------------------------

# The properties a set of sections most often gives two values for: how to
# find each in a sentence, the units its value comes in, and the variable a
# value repeated often enough would become.
PROPERTIES = [
    ("Concrete cover", r"\bcover\b(?! meter|\s+(?:concrete|surfaces?|with|the|and|them|it)\b)",
     {"mm"}, "cover"),
    ("Tie wire diameter", r"\bti(?:e|ing) wire\b", {"mm"}, "tie_wire"),
    ("Maximum aggregate size",
     r"\baggregate size\b|\bsize of (?:the )?(?:coarse |large )?aggregate\b", {"mm"}, "max_aggregate"),
    ("Water-cementitious ratio", r"\bw/cm?\b|water[- ]cement(?:itious)?(?:\s+materials?)?\s+ratio",
     {"ratio"}, "wc_ratio"),
    ("Slump", r"\bslump\b", {"mm"}, "slump"),
    ("Air content", r"\bair content\b", {"%"}, "air_content"),
    ("Chloride content", r"\bchloride (?:ion )?content\b", {"%"}, "chloride_limit"),
    ("Curing period", r"\bcur(?:e|ed|ing)\b(?: period)?", {"days"}, "curing_days"),
    ("Concrete temperature",
     r"\bconcrete temperature\b|\btemperature of (?:the )?(?:fresh |placed )?concrete\b", {"°C"},
     "concrete_temperature"),
    ("Clear spacing between bars",
     r"\bclear(?:ance| spacing| distance)? between (?:reinforcing |parallel )?bars\b", {"mm"}, "bar_spacing"),
    ("Cement content", r"\bcement(?:itious)? (?:materials? )?content\b", {"kg/m3"}, "cement_content"),
    ("Zinc coating thickness", r"\b(?:zinc|galvani[sz]\w*) coating\b", {"µm", "g/m2"}, "galvanizing"),
    ("Dry film thickness", r"\bD\.?F\.?T\b|\bdry film thickness\b", {"µm", "mils"}, "dft"),
]
VALUE = re.compile(
    r"(?<![\w/.])(\d+(?:\.\d+)?)\s*(mm|MPa|N/mm2|N/mm²|N/sq\.? mm|kg/m3|kg/m³|kg/cu\.? ?m|g/m2|g/m²|%|percent"
    r"|°C|deg(?:rees)? C|days?|hours?|µm|microns?|mils)(?!\w)", re.I)
RATIO = re.compile(r"(?<![\d.])0\.\d{2}(?!\d)")
NEAR = 90          # how far after the property's name its value is looked for

REPEATABLE = [
    ("Concrete class", re.compile(r"\bC\d{2,3}/\d{2,3}\b"), "concrete_class"),
    ("Steel grade", re.compile(r"\b(?:S(?:235|275|355|420|460)(?:J[0R2]|K2|N|M)?(?:\s?H)?|B500[ABC])\b"),
     "steel_grade"),
    ("Exposure class", re.compile(r"\bX(?:C[1-4]|D[1-3]|S[1-3]|F[1-4]|A[1-3])\b"), "exposure_class"),
]
REPEATS = 3        # how many times a value is written out before it is worth one variable


def _values_after(name: str, rule: re.Pattern, units: set, sentence: str) -> list[str]:
    """The values a sentence gives the property: those in its units that come
    soonest after its name, before another property's name takes over."""
    out = []
    for hit in rule.finditer(sentence):
        window = sentence[hit.end():hit.end() + NEAR]
        if "ratio" in units:
            found = [m.group(0) for m in RATIO.finditer(window)]
        else:
            found = [f"{_number(m.group(1))} {_unit(m.group(2))}" for m in VALUE.finditer(window)]
            found = [v for v in found if v.split(" ", 1)[1] in units]
        if found:
            out.append(found[0])
    return list(dict.fromkeys(out))


def _number(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", text or "") if s.strip()]


def _brief(text: str, length: int = 140) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= length else text[:length - 1].rstrip() + "…"


def check(sections: Sequence[Mapping[str, Any]], chosen: Mapping[str, str],
          values: Mapping[str, str], options: Sequence[Mapping[str, Any]],
          table: Standards, basis_key: str = "standards") -> dict:
    """Everything worth a second look across a set of sections.

    ``sections`` each carry ``id``, ``number``, ``title`` and ``nodes``. What
    comes back is grouped: ``references``, ``standards``, ``outdated``,
    ``discrepancies``, ``repeated`` and ``setup``. Each item says where it is
    (section, paragraph path, a few words of the text) and what is the
    matter; some carry a ``fix`` the page can offer.
    """
    where = index(sections, chosen)
    basis = basis_of(chosen.get(basis_key, ""))
    report: dict[str, list[dict]] = {k: [] for k in
                                     ("references", "standards", "outdated", "discrepancies",
                                      "repeated", "setup")}
    known_options = {o["key"]: {specs._norm(c) for c in o.get("choice_list", [])} for o in options}

    issued: list[tuple[Mapping[str, Any], dict]] = []
    for s in sections:
        for n in specs.number(s["nodes"], chosen):
            if n["level"] == specs.NOTE:
                continue
            if n["included"]:
                issued.append((s, n))
            # Conditions that name questions or answers nobody can give.
            for part in (n.get("when") or "").split("&"):
                if not part.strip():
                    continue
                key, _, wanted = part.partition("!=" if "!=" in part else "=")
                key = key.strip()
                if key not in known_options:
                    report["setup"].append(_item(s, n, f"its condition asks about \"{key}\", "
                                                       "which is not one of the options"))
                elif known_options[key]:
                    odd = [w for w in wanted.split("|") if specs._norm(w) not in known_options[key]]
                    if odd:
                        report["setup"].append(_item(s, n, f"its condition names \"{'|'.join(odd)}\", "
                                                           f"which is not a choice of \"{key}\""))

    typed_links = 0
    std_seen: dict[str, dict] = {}
    editions: dict[str, set] = defaultdict(set)
    for s, n in issued:
        text = n["text"]
        # Live references that point nowhere.
        for m in REF.finditer(text):
            found = lookup(m.group(1), s["number"], where)
            if found.get("problem"):
                report["references"].append(_item(s, n, f"{{ref:{m.group(1)}}} {found['problem']}",
                                                  severity="error"))
            elif found["kind"] in ("article", "paragraph", "part") and not found["hit"]["included"]:
                report["references"].append(_item(
                    s, n, f"refers to {found['hit']['text'][:60]!r}, which this project's choices "
                          "leave out", severity="error"))
        # Typed references: to sections not issued, under the wrong title, or
        # simply not live yet.
        plain = REF.sub("", text)
        for m in TYPED_SECTION.finditer(plain):
            number = m.group("number")
            target = where.get(_section_key(number))
            if target is None:
                report["references"].append(_item(
                    s, n, f"refers to Section {number}, which is not in this specification",
                    severity="warning"))
                continue
            if _section_key(number) == _section_key(s["number"]):
                continue
            typed_links += 1
            if m.group("title") and _article_key(m.group("title")) != _article_key(target["title"]):
                report["discrepancies"].append(_item(
                    s, n, f"cites Section {number} as \"{m.group('title').strip()}\"; it is "
                          f"\"{title_case(target['title'])}\"", fix={"action": "link"}))
        mine = where.get(_section_key(s["number"]))
        for m in TYPED_ARTICLE.finditer(plain):
            if mine and not any(h["path"] == m.group("path") for h in mine["articles"].values()):
                report["references"].append(_item(
                    s, n, f"refers to {m.group(0)}, and this section has no article {m.group('path')}",
                    severity="error"))
            elif mine:
                typed_links += 1

        # Standards.
        for m in STANDARD.finditer(plain):
            ref = m.group(0)
            key = std_key(ref)
            year = std_year(m)
            if year:
                editions[key].add((year, ref.strip()))
            gone = table.outdated(ref, year)
            if gone:
                report["outdated"].append(_item(
                    s, n, f"{ref.strip()} is out of date" + (f"; use {gone['new']}" if gone["new"] else "")
                          + (f" ({gone['note']})" if gone["note"] else ""),
                    severity="warning", fix={"action": "replace", "old": gone["old"], "new": gone["new"]}
                    if _single(gone["new"]) else None, extra={"ref": ref.strip()}))
            side = family(ref)
            if basis in ("bs", "us") and side != basis and not table.equivalent(ref):
                seen = std_seen.setdefault(key, {"ref": ref.strip(), "places": []})
                seen["places"].append(_where(s, n))

    for key, seen in sorted(std_seen.items()):
        other = "BS EN" if basis == "bs" else "ACI/ASTM"
        report["standards"].append({
            "severity": "warning", "section": seen["places"][0]["section"],
            "row_id": seen["places"][0]["row_id"], "path": seen["places"][0]["path"],
            "text": ", ".join(f"{p['section']} {p['path']}" for p in seen["places"][:8])
                    + (" …" if len(seen["places"]) > 8 else ""),
            "message": f"{seen['ref']} has no {other} equivalent recorded, so it stays as written "
                       f"({len(seen['places'])} place{'s' if len(seen['places']) != 1 else ''})",
            "ref": seen["ref"]})

    for key, found in editions.items():
        years = sorted({y for y, _ in found})
        if len(years) > 1:
            report["discrepancies"].append({
                "severity": "warning", "section": "", "row_id": None, "path": "",
                "text": ", ".join(sorted({r for _, r in found})),
                "message": f"{key} is cited in {len(years)} editions: {', '.join(map(str, years))}"})

    # The same property given different values; and one value given so often
    # that it should be written once.
    for name, pattern, units, variable in PROPERTIES:
        rule = re.compile(pattern, re.I)
        found: dict[str, list[dict]] = defaultdict(list)
        for s, n in issued:
            if n["level"] in ("PRT", "ART"):
                continue
            for sentence in _sentences(specs.VARIABLE.sub("", REF.sub("", n["text"]))):
                for value in _values_after(name, rule, units, sentence):
                    found[value].append(_item(s, n, _brief(sentence)))
        if len(found) > 1:
            report["discrepancies"].append({
                "severity": "info", "section": "", "row_id": None, "path": "", "property": name,
                "message": f"{name} is given as " + ", ".join(
                    f"{v} ({len(places)}×)" for v, places in _by_count(found)),
                "places": [dict(p, value=v) for v, places in _by_count(found) for p in places[:6]]})
        for value, places in _by_count(found):
            if len(places) >= REPEATS:
                report["repeated"].append(_repeat(f"{name} {value}", value, places, variable,
                                                  prop=name))

    # Grades and classes written out often enough to be one variable.
    for kind, rule, variable in REPEATABLE:
        places: dict[str, list[dict]] = defaultdict(list)
        for s, n in issued:
            for m in rule.finditer(specs.VARIABLE.sub("", REF.sub("", n["text"]))):
                places[m.group(0)].append(_item(s, n, _brief(n["text"], 90)))
        for value, where_found in _by_count(places):
            if len(where_found) >= REPEATS:
                report["repeated"].append(_repeat(f"{kind} {value}", value, where_found, variable))

    # Paragraphs said more than once.
    same: dict[str, list[dict]] = defaultdict(list)
    for s, n in issued:
        if n["level"] in ("PRT", "ART", specs.TABLE) or len(n["text"]) < 60:
            continue
        same[specs._norm(n["text"])].append(_item(s, n, _brief(n["text"])))
    for text, places in sorted(same.items(), key=lambda kv: -len(kv[1])):
        if len(places) > 1:
            report["repeated"].append({
                "severity": "info", "section": "", "row_id": None, "path": "",
                "message": _said_again(places),
                "text": places[0]["text"], "places": places})

    # Words used and never given a value.
    for s, n in issued:
        for name in specs.VARIABLE.findall(n["text"]):
            if not values.get(name):
                report["setup"].append(_item(s, n, f"{{{{{name}}}}} has no value for this project"))

    report["typed_links"] = [{"count": typed_links}] if typed_links else []
    report["counts"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    return report


def _single(ref: str) -> bool:
    """Whether a replacement is one standard, which can be put in for another
    without a person choosing which part applies."""
    found = list(STANDARD.finditer(ref or ""))
    return len(found) == 1 and found[0].group(0).strip() == (ref or "").strip()


def _unit(unit: str) -> str:
    unit = unit.lower()
    return {"n/mm²": "MPa", "n/mm2": "MPa", "mpa": "MPa", "percent": "%", "microns": "µm",
            "micron": "µm", "kg/m³": "kg/m3", "kg/cu. m": "kg/m3", "kg/cu.m": "kg/m3",
            "kg/cu m": "kg/m3", "g/m²": "g/m2", "day": "days", "hour": "hours", "deg c": "°C",
            "degrees c": "°C", "degree c": "°C", "°c": "°C"}.get(unit, unit)


def _said_again(places: list[dict]) -> str:
    sections_in = list(dict.fromkeys(p["section"] for p in places))
    if len(sections_in) == 1:
        return (f"The same paragraph appears {len(places)} times in {sections_in[0]}: say it once, "
                "or once under a heading that covers each case")
    return (f"The same paragraph appears in {', '.join(sections_in[:-1])} and {sections_in[-1]}: "
            "keep it in one and refer to it from the others with ¶, so a change is made once")


def _by_count(found: Mapping[str, list]) -> list[tuple[str, list]]:
    return sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _repeat(what: str, value: str, places: list[dict], variable: str, prop: str = "") -> dict:
    sections_in = len({p["section"] for p in places})
    return {"severity": "info", "section": "", "row_id": None, "path": "", "value": value,
            "message": f"{what} is written out {len(places)} times"
                       + (f" across {sections_in} sections" if sections_in > 1 else "")
                       + "; as one word filled in per project it would be changed in one place",
            "places": places[:8], "fix": {"action": "variable", "value": value, "suggest": variable,
                                                 "property": prop}}


def _where(s: Mapping[str, Any], n: Mapping[str, Any]) -> dict:
    return {"section": s["number"], "row_id": s.get("id"), "path": n.get("path", "")}


def _item(s: Mapping[str, Any], n: Mapping[str, Any], message: str, severity: str = "info",
          fix: dict | None = None, extra: dict | None = None) -> dict:
    return {**_where(s, n), "severity": severity, "message": message,
            "text": _brief(n.get("text", "")), "fix": fix, **(extra or {})}


def replace_standard(text: str, old: str, new: str) -> tuple[str, int]:
    """Every citation of ``old`` (any edition, any spacing, any of its parts
    when it names none) replaced by ``new``."""
    key = std_key(old)
    year_limit = None
    match = STANDARD.search(old)
    if match:
        year_limit = std_year(match)
    count = 0

    def one(m: re.Match) -> str:
        nonlocal count
        found = std_key(m.group(0))
        if found != key and not found.startswith(key + "-"):
            return m.group(0)
        if year_limit is not None and (std_year(m) is None or std_year(m) > year_limit):
            return m.group(0)
        count += 1
        return new

    return STANDARD.sub(one, text or ""), count


def make_variable(text: str, value: str, name: str, prop: str = "") -> tuple[str, int]:
    """Every standalone ``value`` in the text made ``{{name}}`` — or, for a
    property's value, only where it is given as that property, so a 75 mm
    that is not the cover stays as it is."""
    number, _, unit = value.partition(" ")
    spaced = re.escape(number) + (r"\s*" + re.escape(unit) if unit else "")
    rule = re.compile(r"(?<![\w/.])" + spaced + r"(?![\w/])")
    wanted = "{{%s}}" % name
    rules = [(re.compile(p, re.I), units) for n, p, units, _v in PROPERTIES if n == prop]
    if not rules:
        return rule.subn(wanted, text or "")
    near, _units = rules[0]
    text = text or ""
    # The value that comes soonest after each mention of the property.
    starts = set()
    for hit in near.finditer(text):
        first = rule.search(text, hit.end(), hit.end() + NEAR)
        if first:
            starts.add(first.start())
    count = 0

    def one(m: re.Match) -> str:
        nonlocal count
        if m.start() not in starts:
            return m.group(0)
        count += 1
        return wanted

    return rule.sub(one, text), count
