# Company procedures: the project journey

The **Procedures** tab on every project. It walks the project through PRC-PM-02 and the
procedures around it (PM-03 to PM-19, EN-01, EN-02), station by station from award to
close-out: questions decide which of the 259 actions apply, and each action is cleared as
Done or N/A, with notes and target dates. Each action cites the procedure section it comes from.

| File | What it is |
|---|---|
| `library.json` | The content: stations, questions and actions. Edit this when a procedure is revised. |
| `journey.html` | The page itself, with `/*LIBRARY*/` and `/*SERVER*/` placeholders filled by `app/procedures.py`. |
| `check_library.py` | Checks the library (unique ids, every condition pointing at a real question and answer). Also writes the stand-alone offline page. |

Each project's progress is stored on the server (table `project_journeys`), so the whole team
sees one copy. Changes are sent as only the keys they touch, so two people clearing different
actions at once both keep their work. Keep action ids stable: progress is stored against them.

**Ongoing projects** open on the same journey; tick off what is already done station by station
(the List view has a checkbox per action). **Sibline Port** starts from its own checklist
(S25001-0100D): `seed/journey-sibline-port.json`, read the first time its tab is opened.
A project whose code matches another `seed/journey-<code>.json` file starts from that the same way.

What is overdue or waiting on a question also shows in the project's **Needs attention** view.

## Updating the procedures

1. Edit `library.json` (an action has `id`, `ph`, `t`, `d`, `who`, `rec`, `ref`, and optionally
   `freq`, `topic`, `tip` and `when`; see the conditions note below).
2. Run `python check_library.py` from this folder; it refuses if anything is inconsistent.
3. Restart the site.

**`when`** says which answers make an action apply, e.g. `{"process":"bim","type":["building","building_ext"]}`.
All keys must match; a list means "any of these". `{"any":[...]}` means either condition. No `when` applies to every project.
