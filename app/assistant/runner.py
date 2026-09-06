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

from .tools import READ_ONLY, ToolError, describe, run

# How many times round the loop before it has to answer in words. Enough to
# look something up, look up what that turned out to point at, and then say
# something; not enough to spend a minute of somebody's afternoon.
MAX_ROUNDS = 6

# A single answer should not be able to rewrite the programme. More than this
# many changes is a conversation, not a request.
MAX_STAGED = 12

# How much of the conversation goes back each time. Long enough to follow a
# thread, short enough not to send the afternoon back on every question.
KEEP_TURNS = 12


SYSTEM = """You are the assistant inside Project Control, a design-programme \
control app used by a project manager on {project}.

Today is {today}. Every date you say or accept is dd/mm/yyyy.

You have tools that read this project and tools that change it. Use them — never \
answer from memory, never guess a date, a percentage or a WBS number. If you have \
not read it with a tool in this conversation, look it up.

How to work:
* Turn what the reader said into exact deliverables first. "the design basis" is \
  a phrase; 3.1 is a deliverable. Use find_deliverables when you are not certain.
* Read before you change. Check where a line actually is before setting it.
* One question can need several tools. Chain them.
* If a tool tells you something is ambiguous, ask the reader which they meant \
  rather than picking one.

About changing things: a tool that changes something does not change it \
immediately — it is staged for the reader to approve, and the page shows them \
the list. So say plainly what you have staged and why, in one or two sentences. \
Do not claim it is done; say what will happen when they press Apply.

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
        }


def _system(project: Mapping[str, Any], today: str) -> dict[str, str]:
    from ..dates import to_display

    return {
        "role": "system",
        "content": SYSTEM.format(
            project=f"{project.get('code')} — {project.get('name')}",
            today=to_display(today),
        ),
    }


def _trim(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The recent conversation, without the tool traffic that produced it.

    Sending every tool result back on every question is how a chat gets slow
    and expensive. What the assistant said and what the reader asked is enough
    to follow a thread; anything it needs again it can look up again, which is
    also how it stays current.
    """
    kept = [dict(turn) for turn in history
            if turn.get("role") in ("user", "assistant") and turn.get("content")]
    return kept[-KEEP_TURNS:]


def ask(project: Mapping[str, Any], question: str, key: str, model: str = "",
        history: Sequence[Mapping[str, Any]] = (), today: str = "") -> Answer:
    """One question, answered — with anything it wants to change staged."""
    from ..groq import GroqError, chat
    from ..service import as_dict, today as today_is

    project = as_dict(project)
    answer = Answer()
    asked = " ".join(str(question or "").split())
    if not asked:
        answer.trouble = "Ask it something"
        return answer

    project_id = int(project["id"])
    messages: list[dict[str, Any]] = [_system(project, today or today_is())]
    messages.extend(_trim(history))
    messages.append({"role": "user", "content": asked})

    catalogue = describe()
    for round_number in range(1, MAX_ROUNDS + 1):
        answer.rounds = round_number
        try:
            said = chat(key, messages, catalogue, model)
        except GroqError as exc:
            answer.trouble = str(exc)
            return answer

        calls = said.get("tool_calls") or []
        if not calls:
            answer.text = str(said.get("content") or "").strip()
            break

        # The model's own turn has to go back verbatim, or the tool results
        # that follow it have nothing to attach to.
        messages.append({
            "role": "assistant",
            "content": said.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            messages.append(_do(call, project_id, answer))

    else:
        # Out of rounds with nothing said. Better to admit that than to leave
        # the reader looking at an empty box.
        answer.text = answer.text or (
            "I looked at several things and could not get to an answer. Try asking "
            "for one thing at a time.")

    if not answer.text and not answer.staged:
        answer.text = "I have nothing to say about that."

    answer.history = [
        *_trim(history),
        {"role": "user", "content": asked},
        {"role": "assistant", "content": answer.text},
    ]
    return answer


def _do(call: Mapping[str, Any], project_id: int, answer: Answer) -> dict[str, Any]:
    """One tool call: run it, or stage it, and say which."""
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    call_id = str(call.get("id") or name)

    try:
        arguments = json.loads(function.get("arguments") or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments were not an object")
    except (TypeError, ValueError) as exc:
        return _result(call_id, name, {"error": f"Those arguments did not parse: {exc}"})

    if name not in answer.used:
        answer.used.append(name)

    try:
        outcome = run(name, project_id, arguments)
    except ToolError as exc:
        # A wrong reference is something the model can correct on the next
        # round, so it is told rather than the whole answer failing.
        return _result(call_id, name, {"error": str(exc)})
    except Exception as exc:                          # noqa: BLE001 - never break the chat
        return _result(call_id, name, {"error": f"That did not work: {exc}"})

    if name in READ_ONLY:
        if isinstance(outcome, dict) and outcome.get("kind") in ("open_view", "presentation"):
            answer.links.append(outcome)
        return _result(call_id, name, outcome)

    if len(answer.staged) >= MAX_STAGED:
        return _result(call_id, name, {
            "error": f"That is more than {MAX_STAGED} changes in one answer. Tell the "
                     f"reader what else needs doing and let them ask again."})

    staged = dict(outcome)
    staged["id"] = f"{name}-{len(answer.staged) + 1}"
    answer.staged.append(staged)
    return _result(call_id, name, {
        "staged": True,
        "change": staged.get("says", name),
        "note": "Not done yet — it is waiting for the reader to press Apply. "
                "Tell them what you have staged.",
    })


def _result(call_id: str, name: str, payload: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(payload, default=str)[:12000],
    }


def staged_summary(staged: Sequence[Mapping[str, Any]]) -> str:
    """The staged changes in one line, for a flash message."""
    if not staged:
        return "Nothing to apply"
    if len(staged) == 1:
        return str(staged[0].get("says") or "One change applied")
    return f"{len(staged)} changes applied"


# --- doing what was staged --------------------------------------------------

class ApplyError(Exception):
    """A staged change that cannot be applied, said in words."""


def apply(project_id: int, actions: Sequence[Mapping[str, Any]], user_id: int,
          data_date: str = "") -> list[dict[str, Any]]:
    """Carries out what the reader approved.

    Every one goes through the same service function the screens post to, so a
    change made here is a change made the ordinary way — the same validation,
    the same cascade, the same history. The caller has already checked that
    this person may write to this project.
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

        else:
            raise ApplyError(f"There is nothing called {kind!r} to apply")

        done.append({"kind": kind, "says": says})

    return done


def _own_task(project_id: int, task_id: Any) -> dict[str, Any]:
    """The deliverable, checked to be this project's before anything touches it."""
    from ..db import query_one

    row = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if row is None:
        raise ApplyError("That deliverable is no longer on this project")
    return dict(row)
