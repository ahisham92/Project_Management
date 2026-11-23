"""Check the procedure library, and build the stand-alone "PM Procedure Checklist.html".

Project Control reads library.json and journey.html directly (see app/procedures.py),
so after editing the library only the check is needed. Usage, from this folder:
    python check_library.py
which also writes the stand-alone page (runs offline, keeps its data in the browser)
next to this file.

It checks the library first (unique ids, known stations, every condition pointing
at a real question and answer) and stops with a list of problems if anything is wrong.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / "journey.html"
LIBRARY = HERE / "library.json"
OUTPUT = HERE / "PM Procedure Checklist.html"


def check(lib):
    problems = []
    questions = {q["id"]: q for q in lib["questions"]}
    stations = {p["id"] for p in lib["phases"]}

    def check_condition(cond, where):
        for key, want in (cond or {}).items():
            if key == "any":
                for sub in want:
                    check_condition(sub, where)
                continue
            q = questions.get(key)
            if not q or "opts" not in q:
                problems.append(f"{where}: unknown question '{key}'")
                continue
            allowed = {o[0] for o in q["opts"]}
            for v in want if isinstance(want, list) else [want]:
                if v not in allowed:
                    problems.append(f"{where}: '{key}' has no answer '{v}' (allowed: {sorted(allowed)})")

    seen = set()
    for it in lib["items"]:
        if it["id"] in seen:
            problems.append(f"duplicate action id '{it['id']}'")
        seen.add(it["id"])
        if it["ph"] not in stations:
            problems.append(f"{it['id']}: unknown station '{it['ph']}'")
        for field in ("t", "ref"):
            if not it.get(field):
                problems.append(f"{it['id']}: missing '{field}'")
        check_condition(it.get("when"), it["id"])

    qids = [q["id"] for q in lib["questions"]]
    for q in lib["questions"]:
        if qids.count(q["id"]) > 1:
            problems.append(f"duplicate question id '{q['id']}'")
        check_condition(q.get("show"), "question " + q["id"])
    return sorted(set(problems))


def main():
    lib = json.loads(LIBRARY.read_text(encoding="utf-8"))
    problems = check(lib)
    if problems:
        print("Library has problems, nothing was built:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    template = TEMPLATE.read_text(encoding="utf-8")
    if "/*LIBRARY*/" not in template:
        sys.exit("Template is missing the /*LIBRARY*/ placeholder.")
    html = template.replace("/*LIBRARY*/", json.dumps(lib, ensure_ascii=False, indent=0))
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Built {OUTPUT.name}: {len(lib['questions'])} questions, "
          f"{len(lib['items'])} actions, {len(lib['phases'])} stations.")


if __name__ == "__main__":
    main()
