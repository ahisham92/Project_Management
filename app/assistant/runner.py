"""The loop: a question, some tool calls, an answer.

The shape is the ordinary one — ask the model, run what it asks for, ask again
with the results — with two rules that make it safe to point at a live project.

**Reading runs; changing is staged.** A tool that would change something is not
run. It comes back described, in the words a person would use, and the page
shows the list with an Apply button. The model can be confidently wrong about
which deliverable "the design basis one" is, and the cost of that should be a
sentence to correct rather than a schedule to unpick.

**It is bounded.** A fixed number of rounds, a fixed number of staged changes,
and a project id that comes from the URL rather than from anything the model
said. A loop that cannot end and a tool that can reach another project are the
two ways this sort of thing goes wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import edits
from .common import ApplyError
from .tools import READ_ONLY, ToolError, describe, run

# How many times round the loop before it has to answer in words. Enough to
# look something up, look up what that turned out to point at, and then say
# something; not enough to spend a minute of somebody's afternoon.
MAX_ROUNDS = 6

# A single answer should not be able to rewrite the programme. More than this
# many changes is a conversation, not a request.
MAX_STAGED = 12

# How much of the conversation goes back each time.
#
# A chat that sends its whole history on every question costs more with every
# question — the twentieth costs several times the first, for a conversation
# nobody thinks of as long. So the recent turns go back word for word, and
# everything before them goes as one short note listing what was asked. That
# note is built here rather than by asking the model to write one, which would
# cost a call of its own; it is a running index, not a précis.
#
# The effect is that a conversation costs about the same on its fiftieth
# question as on its fourth.
KEEP_TURNS = 6

# How many earlier questions the note lists before it stops.
KEEP_NOTED = 24


SYSTEM = """You are Carmen, the assistant inside Project Control — a design-programme \
control app used by a project manager on {project}.

Today is {today}. Every date you say or accept is dd/mm/yyyy.

You have tools that read this project and tools that change it, and between them \
they reach every tab: progress, the schedule and its dependencies, the budget and \
the timesheet, both registers of minutes, and the setup sheet itself — the project's \
settings, its trades and the office that carries each, sections, workflow steps, \
teams and holidays, the deliverable list and how each line is split between the \
trades. Use them — never answer from memory, never guess a date, a percentage or a \
WBS number. If you have not read it with a tool in this conversation, look it up.

How to work:
* Turn what the reader said into exact deliverables first. "the design basis" is \
  a phrase; 3.1 is a deliverable. Use find_deliverables when you are not certain.
* Read before you change. Check where a line actually is before setting it, and \
  read setup_sheet before changing anything on the setup sheet.
* One question can need several tools. Chain them.
* If a tool tells you something is ambiguous, ask the reader which they meant \
  rather than picking one.
* A change that touches every deliverable — a trade taking a share of all of them, \
  say — is one call to share_across, not fifty calls to set_trade_split.
* Somebody can attach a file to a question — a drawing register, a client\'s letter, \
  a programme. Read what is in it and answer from it; where it says something that \
  should be recorded on the project, stage the change rather than only describing it.
* An attached .xlsx is usually one of this project\'s own exports: the setup sheet, the \
  programme\'s dates, or the dependencies. Use read_workbook to see what is in it, tell \
  the reader what it holds and what importing it would change, then stage import_workbook. \
  Importing the setup sheet replaces the deliverable list, so say so before you stage it.

About changing things: a tool that changes something does not change it \
immediately — it is staged for the reader to approve, and the page shows them \
the list. So say plainly what you have staged and why, in one or two sentences. \
Do not claim it is done; say what will happen when they press Apply.

One guard you do not get past: changes to the setup sheet — settings, trades, \
offices, sections, workflow steps, teams, the deliverable list and the trade split \
— only apply for somebody with manager access who has unlocked the Setup tab, the \
same as making the change by hand. Stage it anyway; if it is refused for that, tell \
them to unlock Setup and ask again.

A deliverable that has been submitted and is waiting for the client's Code A is \
neither late nor behind — the work is issued and the review is the client's. Say \
it is with the client and how long they have had it. A Code B or C hands it back \
and it is ours again from that moment.

Answer in plain English, short. Figures in a small table or a short list, never \
a wall of prose. Do not repeat the raw tool output back — say what it means. If \
the numbers say something the reader would not want to hear, say it anyway.
"""


@dataclass
class Answer:
    """What one question produced."""
    text: str = ""
    staged: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    rounds: int = 0
    trouble: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    spent: dict[str, int] = field(default_factory=dict)
    from_cache: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": not self.trouble,
            "text": self.text,
            "staged": self.staged,
            "links": self.links,
            "used": self.used,
            "rounds": self.rounds,
            "error": self.trouble,
            "history": self.history,
            "spent": self.spent,
            "from_cache": self.from_cache,
        }

    def add(self, spent: Mapping[str, int]) -> None:
        """What one round of the loop cost, added to the rest."""
        for name, count in (spent or {}).items():
            self.spent[name] = self.spent.get(name, 0) + int(count or 0)


def _system(project: Mapping[str, Any], today: str) -> str:
    """The standing instruction. Its own field on this API, not a message."""
    from ..dates import to_display

    return SYSTEM.format(
        project=f"{project.get('code')} — {project.get('name')}",
        today=to_display(today),
    )


def _trim(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The recent conversation, and a one-message note of what came before it.

    Sending every tool result back on every question is how a chat gets slow and
    expensive; sending the whole transcript is how it gets steadily worse. What
    the assistant said and what the reader asked in the last few turns is enough
    to follow a thread, and anything else it needs it can look up again — which
    is also how it stays current rather than answering from a stale copy.
    """
    kept = [dict(turn) for turn in history
            if turn.get("role") in ("user", "assistant") and turn.get("content")]
    if len(kept) <= KEEP_TURNS:
        return kept

    earlier, recent = kept[:-KEEP_TURNS], kept[-KEEP_TURNS:]
    note = _note(earlier)
    # The note is a user message because that is the only role a conversation
    # may open with, and these are always the oldest turns.
    return ([{"role": "user", "content": note}] if note else []) + recent


def _note(earlier: Sequence[Mapping[str, Any]]) -> str:
    """Earlier in this conversation, in a few lines rather than in full."""
    asked = [" ".join(str(turn.get("content") or "").split())[:110]
             for turn in earlier if turn.get("role") == "user"]
    asked = [line for line in asked if line][-KEEP_NOTED:]
    if not asked:
        return ""
    listed = "\n".join(f"- {line}" for line in asked)
    return ("Earlier in this conversation I was asked, in order:\n" + listed +
            "\n\n(The answers are not repeated here. If any of it matters to what "
            "comes next, look it up again with a tool rather than remembering it.)")


def ask(project: Mapping[str, Any], question: str, key: str, model: str = "",
        history: Sequence[Mapping[str, Any]] = (), today: str = "",
        effort: str = "", attachments: Sequence[Mapping[str, Any]] = ()) -> Answer:
    """One question, answered — with anything it wants to change staged."""
    from ..claude import (ClaudeError, DEFAULT_EFFORT, chat, refused, said, spent,
                          tool_calls)
    from ..service import as_dict, today as today_is

    project = as_dict(project)
    answer = Answer()
    asked = " ".join(str(question or "").split())
    if not asked:
        answer.trouble = "Ask it something"
        return answer

    project_id = int(project["id"])
    system = _system(project, today or today_is())

    # Asked before, and nothing on the project has changed since? Then the
    # answer has not changed either — the figures come from the project, and
    # the project has not moved. Handed straight back, for nothing.
    #
    # Only where there is nothing else to carry: a question with a file on it,
    # or one in the middle of a conversation, is answered properly.
    if not attachments and not history:
        from ..service import remembered_answer

        kept = remembered_answer(project_id, asked)
        if kept:
            answer.text = str(kept["answer"])
            answer.used = [w for w in str(kept["tools_used"] or "").split(", ") if w]
            answer.from_cache = True
            answer.history = [{"role": "user", "content": asked},
                              {"role": "assistant", "content": answer.text}]
            return answer

    # A PDF or a picture goes to the model as itself; the words out of a Word
    # or PowerPoint file go in front of the question, said to be what they are.
    from ..reading import as_content

    content = as_content(asked, list(attachments))
    messages: list[dict[str, Any]] = [*_trim(history), {"role": "user", "content": content}]

    catalogue = describe()
    for round_number in range(1, MAX_ROUNDS + 1):
        answer.rounds = round_number
        try:
            reply = chat(key, system, messages, catalogue, model,
                         effort or DEFAULT_EFFORT)
        except ClaudeError as exc:
            answer.trouble = str(exc)
            return answer

        answer.add(spent(reply))

        declined = refused(reply)
        if declined:
            answer.trouble = declined
            return answer

        calls = tool_calls(reply)
        if not calls:
            answer.text = said(reply)
            break

        # Claude's own turn goes back whole — thinking blocks and all. Trimming
        # it is how a tool result ends up with nothing to attach to, and on this
        # model a replayed turn has to be the one that was sent.
        messages.append({"role": "assistant", "content": reply.content})

        # Every result for a turn goes back in one user message. Splitting them
        # across several quietly teaches the model to stop calling tools in
        # parallel, which makes every later answer slower for no reason.
        messages.append({"role": "user",
                         "content": [_do(call, project_id, answer, attachments)
                                     for call in calls]})

    else:
        # Out of rounds with nothing said. Better to admit that than to leave
        # the reader looking at an empty box.
        answer.text = answer.text or (
            "I looked at several things and could not get to an answer. Try asking "
            "for one thing at a time.")

    if not answer.text and not answer.staged:
        answer.text = "I have nothing to say about that."

    # Worth keeping only where the answer is words about the project as it
    # stands. Anything that staged a change, produced a link or went wrong is
    # worked out again next time, because what those produce is not just words.
    if answer.text and not answer.staged and not answer.links and not answer.trouble \
            and not attachments and not history:
        from ..service import remember_answer

        remember_answer(project_id, asked, answer.text, answer.used)

    answer.history = [
        *_trim(history),
        {"role": "user", "content": asked},
        {"role": "assistant", "content": answer.text},
    ]
    return answer


def _do(call: Mapping[str, Any], project_id: int, answer: Answer,
        attachments: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """One tool call: run it, or stage it, and say which."""
    name = str(call.get("name") or "")
    call_id = str(call.get("id") or name)
    arguments = call.get("input")
    if not isinstance(arguments, dict):
        return _result(call_id, {"error": "Those arguments were not an object"}, True)

    if name not in answer.used:
        answer.used.append(name)

    try:
        outcome = run(name, project_id, arguments, attachments)
    except ToolError as exc:
        # A wrong reference is something the model can correct on the next
        # round, so it is told rather than the whole answer failing.
        return _result(call_id, {"error": str(exc)}, True)
    except Exception as exc:                          # noqa: BLE001 - never break the chat
        return _result(call_id, {"error": f"That did not work: {exc}"}, True)

    if name in READ_ONLY:
        if isinstance(outcome, dict) and outcome.get("kind") in ("open_view", "presentation",
                                                                 "document"):
            answer.links.append(outcome)
        return _result(call_id, outcome)

    if len(answer.staged) >= MAX_STAGED:
        return _result(call_id, {
            "error": f"That is more than {MAX_STAGED} changes in one answer. Tell the "
                     f"reader what else needs doing and let them ask again."}, True)

    staged = dict(outcome)
    staged["id"] = f"{name}-{len(answer.staged) + 1}"
    answer.staged.append(staged)
    return _result(call_id, {
        "staged": True,
        "change": staged.get("says", name),
        "note": "Not done yet — it is waiting for the reader to press Apply. "
                "Tell them what you have staged.",
    })


def _result(call_id: str, payload: Any, failed: bool = False) -> dict[str, Any]:
    """One tool result, in the shape the Messages API wants it.

    A failure comes back as a result marked as one rather than being dropped:
    a tool call with no result at all is what makes the next turn incoherent.
    """
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": json.dumps(payload, default=str)[:12000],
    }
    if failed:
        block["is_error"] = True
    return block


def staged_summary(staged: Sequence[Mapping[str, Any]]) -> str:
    """The staged changes in one line, for a flash message."""
    if not staged:
        return "Nothing to apply"
    if len(staged) == 1:
        return str(staged[0].get("says") or "One change applied")
    return f"{len(staged)} changes applied"


# --- doing what was staged --------------------------------------------------

def apply(project_id: int, actions: Sequence[Mapping[str, Any]], user_id: int,
          data_date: str = "", setup_open: bool = True,
          is_manager: bool = True) -> list[dict[str, Any]]:
    """Carries out what the reader approved.

    Every one goes through the same service function the screens post to, so a
    change made here is a change made the ordinary way — the same validation,
    the same cascade, the same history. The caller has already checked that
    this person may write to this project, and says in ``setup_open`` and
    ``is_manager`` whether they may also edit the setup sheet and the
    programme — which are their own guards on the screens and stay their own
    guards here.
    """
    from ..service import (add_holiday, add_link, load_steps, next_sort_order,
                           record_progress, remove_link, renumber_items, set_status,
                           set_task_dates, today)
    from ..db import execute, insert, query_one

    stamp = data_date or today()
    done: list[dict[str, Any]] = []

    for action in actions:
        kind = str(action.get("kind") or "")
        says = str(action.get("says") or kind)

        if kind in edits.PROGRAMME_KINDS and not is_manager:
            raise ApplyError(
                "Moving the programme takes manager access on this project, the same as "
                "changing a date on the Schedule tab. Ask somebody who has it.")

        if kind in edits.SETUP_KINDS and not setup_open:
            raise ApplyError(
                "That changes the setup sheet, which is locked. Unlock it on the Setup "
                "tab — it takes manager access and the setup password — and ask me again.")

        if kind == "set_progress":
            task = _own_task(project_id, action.get("task_id"))
            if action.get("status_key"):
                set_status(task, str(action["status_key"]), str(action.get("note") or ""),
                           stamp, user_id, load_steps(project_id))
            else:
                record_progress(task, float(action.get("percent") or 0) / 100,
                                str(action.get("note") or ""), stamp, user_id)

        elif kind == "set_dates":
            _own_task(project_id, action.get("task_id"))
            set_task_dates(project_id, int(action["task_id"]), str(action["start"]),
                           str(action["submission"]), bool(action.get("cascade", True)))

        elif kind == "add_link":
            add_link(project_id, int(action["predecessor_id"]), int(action["successor_id"]),
                     float(action.get("lag_days") or 0), str(action.get("link_kind") or "FS"))

        elif kind == "remove_link":
            if not remove_link(project_id, int(action["link_id"])):
                raise ApplyError("That dependency is no longer there")

        elif kind == "raise_item":
            item_id = insert(
                "INSERT INTO meeting_items (project_id, kind, ref, subject, agreement, "
                "owner_code, raised_date, due_date, status, sort_order) "
                "VALUES (?, ?, '', ?, ?, ?, ?, ?, 'open', ?)",
                (project_id, str(action.get("register") or "internal"),
                 str(action.get("subject") or ""), str(action.get("agreed") or ""),
                 str(action.get("owner") or ""), stamp, str(action.get("due") or ""),
                 next_sort_order("meeting_items", project_id)),
            )
            renumber_items(project_id, None)
            says = says + f" (item {item_id})"

        elif kind == "close_item":
            item = query_one("SELECT id FROM meeting_items WHERE id = ? AND project_id = ?",
                             (action.get("item_id"), project_id))
            if item is None:
                raise ApplyError("That item is no longer there")
            execute("UPDATE meeting_items SET status = 'closed', closed_date = ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (str(action.get("closed_on") or stamp), item["id"]))

        elif kind == "add_holiday":
            add_holiday(project_id, action.get("calendar_id"), str(action["date"]),
                        str(action.get("name") or ""))

        elif kind == "minute_meeting":
            meeting_id = _minute(project_id, action, user_id, stamp)
            says = says + f" (meeting {meeting_id})"

        elif kind == "add_minute_items":
            _own_meeting(project_id, action.get("meeting_id"))
            _put_items(project_id, int(action["meeting_id"]), action.get("items") or [], stamp)

        elif kind == "update_minute_item":
            item = query_one("SELECT id FROM meeting_items WHERE id = ? AND project_id = ?",
                             (action.get("item_id"), project_id))
            if item is None:
                raise ApplyError("That item is no longer there")
            fields = dict(action.get("fields") or {})
            allowed = {"subject", "discussion", "agreement", "owner_code", "impact", "due_date"}
            fields = {k: v for k, v in fields.items() if k in allowed}
            if not fields:
                raise ApplyError("There is nothing to change on that item")
            execute("UPDATE meeting_items SET "
                    + ", ".join(f"{name} = ?" for name in fields)
                    + ", updated_at = datetime('now') WHERE id = ?",
                    (*fields.values(), item["id"]))

        elif kind == "issue_details":
            _own_meeting(project_id, action.get("meeting_id"))
            fields = dict(action.get("fields") or {})
            allowed = {"prepared_by", "reviewed_by", "issue_date", "attachment"}
            fields = {k: v for k, v in fields.items() if k in allowed}
            if not fields:
                raise ApplyError("There is nothing to set on that meeting")
            execute("UPDATE meetings SET " + ", ".join(f"{name} = ?" for name in fields)
                    + " WHERE id = ? AND project_id = ?",
                    (*fields.values(), action["meeting_id"], project_id))

        else:
            # Everything on the setup sheet, the deliverable list, the trade
            # split and the timesheet lives in its own module.
            try:
                says = edits.apply_one(project_id, action, user_id, stamp)
            except KeyError:
                raise ApplyError(f"There is nothing called {kind!r} to apply") from None

        done.append({"kind": kind, "says": says})

    return done


def _own_meeting(project_id: int, meeting_id: Any) -> dict[str, Any]:
    from ..db import query_one

    row = query_one("SELECT * FROM meetings WHERE id = ? AND project_id = ?",
                    (meeting_id, project_id))
    if row is None:
        raise ApplyError("That meeting is no longer on this project")
    return dict(row)


def _minute(project_id: int, action: Mapping[str, Any], user_id: int, stamp: str) -> int:
    """A whole set of minutes, written the way the minutes page writes one."""
    from ..db import insert, query_one
    from ..service import load_attendees, next_sort_order, set_attendance

    meeting_id = insert(
        """
        INSERT INTO meetings (project_id, kind, ref, title, purpose, meeting_date,
                              meeting_time, location, chaired_by, notes, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
        """,
        (project_id, str(action.get("register") or "client"), str(action.get("ref") or ""),
         str(action.get("title") or ""), str(action.get("purpose") or ""),
         str(action.get("meeting_date") or stamp), str(action.get("meeting_time") or ""),
         str(action.get("location") or ""), str(action.get("chaired_by") or ""), user_id),
    )

    # Somebody named in the minutes who is not on the roster joins it, because
    # the alternative is a set of minutes with an attendance table of nobody.
    roster = {str(a["name"]).strip().lower(): a["id"] for a in load_attendees(project_id)}
    present: list[int] = []
    invited: list[int] = []
    for person in action.get("attendees") or []:
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        found = roster.get(name.lower())
        if found is None:
            found = insert(
                "INSERT INTO attendees (project_id, name, organisation, job_title, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, name[:120], str(person.get("organisation") or "")[:120],
                 str(person.get("job_title") or "")[:120],
                 next_sort_order("attendees", project_id)),
            )
            roster[name.lower()] = found
        invited.append(found)
        if person.get("present", True):
            present.append(found)
    if invited:
        set_attendance(meeting_id, present, invited)

    _put_items(project_id, meeting_id, action.get("items") or [], stamp)
    return meeting_id


def _put_items(project_id: int, meeting_id: int, items: Sequence[Mapping[str, Any]],
               stamp: str) -> None:
    """Items onto a meeting, numbered by position rather than by anything said."""
    from ..db import insert, query_one
    from ..service import next_sort_order, renumber_items

    when = query_one("SELECT meeting_date FROM meetings WHERE id = ?", (meeting_id,))
    raised = str((when or {})["meeting_date"] or stamp) if when else stamp

    for line in items:
        closed = bool(line.get("closed"))
        insert(
            """
            INSERT INTO meeting_items (project_id, meeting_id, kind, ref, subject, discussion,
                                       agreement, owner_code, impact, raised_date, due_date,
                                       status, closed_date, sort_order)
            SELECT ?, ?, kind, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
              FROM meetings WHERE id = ?
            """,
            (project_id, meeting_id, str(line.get("subject") or ""),
             str(line.get("discussion") or ""), str(line.get("agreement") or ""),
             str(line.get("owner") or ""), str(line.get("impact") or "none"),
             raised, str(line.get("due") or ""),
             "closed" if closed else "open", raised if closed else "",
             next_sort_order("meeting_items", project_id), meeting_id),
        )
    renumber_items(project_id, meeting_id)


def _own_task(project_id: int, task_id: Any) -> dict[str, Any]:
    """The deliverable, checked to be this project's before anything touches it."""
    from ..db import query_one

    row = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if row is None:
        raise ApplyError("That deliverable is no longer on this project")
    return dict(row)
