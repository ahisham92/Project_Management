"""How to use this: what each tab is for, and what every word on it means.

One source of truth for both. The **How to use** tab renders all of it; the
strip at the top of every other tab renders that tab's own entry out of the
same dictionary. Written here rather than in the templates so the two can never
drift apart, and so the wording is something you change in one place.

The rule the entries follow: say what the tab *is*, then what to do on it in
the order you would actually do it, then what to look at when you are only
checking. A definition says what a number means and, where it matters, how it
is worked out — a figure nobody can reproduce is a figure nobody trusts.
"""

from __future__ import annotations

from typing import Any

# --- what each tab is for ---------------------------------------------------
#
# `endpoint` is what the strip matches on, so a tab that gained a second page
# lists both. `terms` names the glossary entries worth having to hand there.

TABS: tuple[dict[str, Any], ...] = (
    {
        "key": "dashboard",
        "name": "Dashboard",
        "endpoints": ("projects.dashboard",),
        "what": "Where the project stands today, on one screen.",
        "start_here": "Read the four tiles, then the S-curve. If nothing is red, you are done here.",
        "steps": (
            "Check <strong>Earned progress</strong> against planned — the variance beside it is the "
            "whole story in one number.",
            "Look at <strong>Float</strong> in the overview: how many days sit between the last "
            "submission and the contract date.",
            "Read <strong>Needs attention</strong> — anything late or behind plan, worst first — and "
            "click through to fix it.",
            "Change the <strong>data date</strong> to read the project as it stood on any past day.",
        ),
        "watch": (
            "Earned below planned means the programme is slipping, whatever the hours say.",
            "Float going negative means the contract date is already gone.",
            "A CPI under 1 means the hours are being spent faster than progress is being earned.",
        ),
        "terms": ("earned progress", "planned progress", "variance", "spi", "cpi", "data date",
                  "float", "weight", "ntp"),
    },
    {
        "key": "progress",
        "name": "Progress",
        "endpoints": ("projects.tasks", "projects.task_history"),
        "what": "Every deliverable, and where each one has got to. This is where progress is recorded.",
        "start_here": "Click the percentage or the status on a row and change it. It saves as you go.",
        "steps": (
            "Filter to <strong>Late</strong> or <strong>Behind plan</strong> to work through what "
            "needs saying first.",
            "Click a row's <strong>progress cell</strong> and pick the workflow step it has reached — "
            "the percentage follows the step, so nobody has to invent a number.",
            "When the client returns comments instead of a Code A, press <strong>Code B / C</strong>: "
            "it raises a revision and asks for the new submission date.",
            "<strong>History</strong> on any row shows every update, who made it and when.",
        ),
        "watch": (
            "Planned progress steps up at each workflow date rather than sliding smoothly — a "
            "deliverable is 40% when it reaches the 40% step, not because half the time has passed.",
            "A line in rework carries its revision number; at the revision limit it turns red.",
        ),
        "terms": ("deliverable", "weight", "planned progress", "earned progress", "workflow step",
                  "code a", "code b", "code c", "revision", "data date", "variance", "office"),
    },
    {
        "key": "schedule",
        "name": "Schedule",
        "endpoints": ("projects.schedule",),
        "what": "The programme: when each deliverable runs, what it waits on, and what is driving the end date.",
        "start_here": "Read the bar chart. Then open the critical path card — that is the run of work that decides the finish.",
        "steps": (
            "Click a bar to open the deliverable, with its dates and its dependencies, and edit "
            "them there.",
            "Change a <strong>start</strong>, a <strong>duration</strong> or a <strong>team</strong> "
            "in the table and everything downstream moves with it, live.",
            "<strong>Squeeze the programme</strong> when a run has to fit between two dates: "
            "name the line it starts on, the line it ends on, and the two dates. Every duration "
            "in between changes by the same proportion — four months into three is every line "
            "times 0.75 — and the run is measured to the last <strong>Code A</strong>. Untick "
            "a line to hold it at the length it has; give a later date to extend instead. Work "
            "it out first — nothing moves until you press Squeeze it, and <strong>Put it "
            "back</strong> restores every date afterwards.",
            "On the diagram, <strong>drag from one box to another</strong> to create a dependency, "
            "and <strong>click a line</strong> to remove one.",
            "Press <strong>Simplify</strong> once the shape is settled — it re-lays the diagram with "
            "the fewest crossings it can find.",
            "<strong>Export to Excel</strong> and import back to move a lot of dates at once.",
        ),
        "watch": (
            "A line that cannot start where it is drawn says which link is holding it and why.",
            "Blue boxes on the diagram are the ends of paths — nothing waits on them.",
            "A submission with holidays in the week before it is flagged: those are the days the "
            "package is being pulled together, and nobody plans for them.",
        ),
        "terms": ("start date", "duration", "submission date", "approval date", "dependency",
                  "fs", "ss", "ff", "sf", "lag", "float", "critical path", "path", "team",
                  "working week", "holiday", "run-up holidays", "squeeze",
                  "recurring meetings", "put it back"),
    },
    {
        "key": "budget",
        "name": "Finance",
        "endpoints": ("projects.budget",),
        "what": "Hours: what was budgeted per trade, what has been booked against it, and what "
                "that says about cost.",
        "start_here": "Book hours at the bottom; compare booked against earned above. "
                      "The gap is the CPI.",
        "steps": (
            "Read each trade's <strong>budget</strong>, <strong>booked</strong> and "
            "<strong>earned</strong> hours side by side.",
            "Check the <strong>CPI</strong> per trade — one trade overspending is easier to fix than "
            "a project average that hides it.",
            "Look at the <strong>estimate at completion</strong>: the budget divided by the CPI, "
            "which is what the project costs if it carries on like this.",
            "<strong>Book hours</strong> at the foot of the tab: the date, the trade, and the "
            "deliverable where you can — that is what makes per-line cost possible later. Every "
            "figure above is built from them.",
            "Delete a wrong entry rather than booking a negative one.",
        ),
        "watch": (
            "Hours booked without a trade still count against the project total.",
            "A high CPI early usually means hours have not been booked yet, not that you are ahead.",
        ),
        "terms": ("budget hours", "booked hours", "earned hours", "cpi", "eac", "trade", "office",
                  "man-month"),
    },
    {
        "key": "resources",
        "name": "Resources",
        "endpoints": ("projects.resources",),
        "what": "How many engineers, on what, in which week — the budget turned into a rota, "
                "and the hours booked read against it.",
        "start_here": "Set the target margin and the working week on Setup; everything here "
                      "follows from those two numbers and the programme.",
        "steps": (
            "Read the <strong>ceiling</strong>: the budget less the target margin. A margin of "
            "12% means the plan is drawn against 88% of the budget, because planning to the "
            "whole of it is planning to make nothing.",
            "Read <strong>planned hours against spent hours</strong> — both cumulative, week by "
            "week. Booked running above planned is the early warning the CPI gives late.",
            "Read <strong>engineers per week</strong>: the same plan in bodies. A few at the "
            "start of a deliverable, more as its submission comes up.",
            "Open <strong>week by week</strong> for the rota itself — a column per trade, with "
            "the hours it wants and the engineers that is. <strong>Type over any of those "
            "numbers</strong>: the hours a week is allowed never move, so what changes is what "
            "each of those engineers is carrying. Clear the box to go back to the plan\u2019s "
            "own figure.",
            "Open <strong>ceiling per deliverable</strong> to see why a line is worth what it is "
            "worth — its weight in the project, times each trade's share of it, with a column "
            "per trade. Every column on both tables sorts.",
            "Watch the <strong>comments reserve</strong>: a share of every workflow line is held "
            "back for answering comments. A line that comes back <strong>Code A first time "
            "never needed it</strong> and the hours are released; one that came back Code B or "
            "C spent it.",
            "Press <strong>Redistribute the savings</strong> to put a trade's released hours "
            "back into that trade's own open deliverables. The notes say which finished lines "
            "paid for it.",
        ),
        "watch": (
            "Nothing after a submission earns hours: that stretch is the client reading it, not "
            "this office working.",
            "A trade with a budget but no share of any deliverable cannot be planned; the tab "
            "names it rather than quietly dropping its hours.",
            "A week's engineers are the sum of its trades, not its hours divided once — three "
            "trades each wanting four tenths of a person is three people, because they are "
            "three different people.",
            "Savings never cross a trade. Marine finishing cleanly is Marine's slack; handing "
            "it to Geotechnical would tell the team that did the careful work that it bought "
            "somebody else the room.",
            "A finalised deliverable is finished with: nothing is redistributed into it, and "
            "its reserve is settled either way.",
        ),
        "terms": ("target margin", "comments reserve", "released hours", "redistribution",
                  "ceiling hours", "planned hours", "booked hours",
                  "engineers per week", "peak week", "hours per week"),
    },
    {
        "key": "period",
        "name": "Summarized Progress",
        "endpoints": ("projects.period",),
        "what": "What moved between two dates — on the programme and in the minutes. The "
                "report you send at the end of a month.",
        "start_here": "Set the two dates and read what changed. Nothing here is stored; it is worked out from the record.",
        "steps": (
            "Pick a <strong>from</strong> and a <strong>to</strong> date.",
            "Read the progress made in that window, by trade and by deliverable.",
            "Read what moved in the <strong>minutes</strong>: the actions closed in the window, "
            "the ones raised in it, and what is still open at the end — from both registers.",
            "<strong>Print / PDF</strong> it — the header carries the project, the dates and the "
            "data date, so a printed page cannot be mistaken for the current one.",
        ),
        "watch": (
            "Progress is attributed to the date it was reported for, not the date it was typed in.",
            "An item counts as closed in the window on the date it was closed, read as the "
            "register stood at the end of it.",
        ),
        "terms": ("data date", "earned progress", "planned progress", "variance",
                  "minuted item", "open", "closed"),
    },
    {
        "key": "minutes",
        "name": "Minutes",
        "endpoints": ("meetings.index", "meetings.meeting", "meetings.agenda"),
        "what": "The client's minutes of meeting, and the action register that comes out of them.",
        "start_here": "Add the meeting, tick who attended, then minute its items one at a time.",
        "steps": (
            "Build the <strong>attendance list</strong> once; after that you only tick who came.",
            "Add a <strong>meeting</strong>, then add its <strong>items</strong>: what was discussed, "
            "what was agreed, who owns it and by when.",
            "Change an item's owner, trades, impact or date by <strong>clicking the cell</strong> in "
            "the row.",
            "Fill in <strong>prepared by</strong>, <strong>reviewed &amp; accepted by</strong> and "
            "the <strong>issue date</strong> on the meeting, and the exported document carries "
            "them — the signatures themselves stay blank rules to sign on.",
            "<strong>Attach</strong> a PDF to a meeting: it is named at the end of the minutes "
            "and compiled onto the end of the exported PDF.",
            "Move a person up or down the <strong>attendance roster</strong> with the arrows — "
            "that is the order the exported table lists them in, and people who did not come "
            "are left off it.",
            "<strong>Export PDF</strong> for the issued document — the letterhead, the grids and "
            "the signature blocks, with the attachments on the end. <strong>Export Word</strong> "
            "for the same thing to edit, or for the register exactly as you have filtered it.",
            "Put a date in <strong>As at</strong> to show a client where things stood then.",
        ),
        "watch": (
            "An item's number is its position in its meeting, so it cannot be typed or collide — "
            "move it with the arrows and it renumbers where it stands, without the page reloading.",
            "The attendance and the meeting details are the first page; the items start on the "
            "page after, the way the practice issues them.",
            "Attachments have to be PDFs, and they are kept in the database so the nightly "
            "backup carries them. They are named in the Word but not embedded in it.",
            "Closing an item asks for the day it was <em>actually</em> closed, because that is what "
            "an As-at reading turns on.",
        ),
        "terms": ("minuted item", "owner", "impact", "open", "closed", "as at", "agenda",
                  "attendee", "trade", "attachment", "attendance order"),
    },
    {
        "key": "internal",
        "name": "Task List",
        "endpoints": ("meetings.week",),
        "what": "This week: everything the project wants of us, compiled from the programme and both registers.",
        "start_here": "Work down the list. Every row is the real record — change it here and it changes everywhere.",
        "steps": (
            "Read the five groups in order: <strong>going out</strong>, <strong>coming back</strong>, "
            "<strong>starting</strong>, <strong>carrying on</strong>, <strong>actions</strong>.",
            "Update a deliverable's progress by clicking its cell — it is the same record the "
            "Progress and Schedule tabs show.",
            "<strong>Close</strong> an action here and it closes in the register it came from.",
            "Press <strong>Start the weekly meeting</strong> — it opens this week's internal meeting, "
            "dated and referenced from the week itself.",
            "Step back and forward a week with the arrows.",
        ),
        "watch": (
            "Anything already late follows you into every week until it is done.",
            "<em>Carrying on</em> is the half a programme never shows: nothing is due, and the days "
            "still have to go in.",
            "The week's worth is each line's shortfall weighted by how much of the project it is.",
        ),
        "terms": ("the week", "carrying on", "the week is worth", "internal register",
                  "weekly meeting", "minuted item", "critical path"),
    },
    {
        "key": "register",
        "name": "Internal register",
        "endpoints": (),
        "what": "Our own action list, kept the same way as the client's minutes but for us.",
        "start_here": "Behind the Internal tab, under Register. Everything the Minutes tab does, this does.",
        "steps": (
            "Raise an item, give it an owner and a date, and close it when it is done.",
            "Read it <strong>as at</strong> a past date when somebody asks where things stood.",
        ),
        "watch": ("The two registers never show each other's items.",),
        "terms": ("internal register", "minuted item", "as at", "open", "closed"),
    },
    {
        "key": "assistant",
        "name": "Carmen",
        "endpoints": ("assistant.index",),
        "what": "The project assistant — ask her anything, or tell her what to change.",
        "start_here": "Type a question. Anything she would change is staged for you to approve before it happens.",
        "steps": (
            "Ask her about the project — “what is late?”, “how did last month go?”, "
            "“what does this week need?”. She reads the same figures the tabs show.",
            "Tell her to change something — “set 1.1 to 40%”, “move 2.3 to start on 15/10/2026”, "
            "“close item 3.1”. It comes back as a <strong>proposal</strong>; nothing happens "
            "until you press Apply.",
            "<strong>Type up a meeting</strong> and say “minute this” — she turns the prose into "
            "numbered items with owners, dates and what each one affects, and fills the Minutes "
            "page. “Correct 3.1 — the owner is MR” fixes one afterwards.",
            "Tell her to change the <strong>setup sheet</strong> — “put Utilities under Cairo”, "
            "“add a trade called Project Manager”, “add a team on Sunday to Thursday”, “add a "
            "deliverable to Marine Design”. Setup has to be unlocked for those to apply, the "
            "same as changing them by hand.",
            "<strong>Attach a file</strong> to a question — a PDF, a Word or PowerPoint file, "
            "a spreadsheet, a picture or plain text. She reads it and answers from it, and it "
            "stays with the conversation.",
            "Ask for a <strong>document</strong> — “give me the minutes as a PDF”, “the "
            "register as Word”, “the programme as a spreadsheet”, “a presentation of last "
            "month” — and she hands back a link to download it.",
            "Every file this project hands out is <strong>kept as it went out</strong>, with "
            "who asked for it and when. A deck built last Tuesday is not the deck those dates "
            "build today, so “let me see the presentation Ola sent” is a question about that "
            "file — and it is on her tab, under Documents.",
            "Every conversation is <strong>kept down the left</strong>. Come back to one and "
            "carry on rather than starting from nothing; rename it, or start a new one. "
            "Whoever runs the project can read everybody’s.",
            "Say “<strong>squeeze 1.1 to 1.6 into 40 working days</strong>” and she works out "
            "what every duration in that run becomes and what it saves, and stages it as one "
            "change.",
            "Ask for a change across <strong>every deliverable</strong> at once — “give the "
            "Project Manager 10% of every deliverable” — and the trades already on each line are "
            "rescaled to fit what is left. It arrives as one proposal, not fifty-five.",
            "Say “<strong>take me to the schedule</strong>” and the page goes there.",
            "Ask for a <strong>presentation</strong> of the work done between two dates and she "
            "builds a PowerPoint you can download.",
            "Ask her to <strong>print</strong> a tab and you get a link that opens straight into "
            "the print dialog, where “Save as PDF” makes the file.",
            "She is in the corner of every other tab too — the button at the bottom right.",
            "An administrator adds the Anthropic API key on the <strong>Setup</strong> tab, once, for everybody.",
        ),
        "watch": (
            "Nothing changes until you press Apply — a model can be confidently wrong about "
            "which deliverable you meant, and that should cost a sentence, not a programme.",
            "She cannot do more than you can: every change goes through the same code a form "
            "posts to, and applying takes the same role as editing the screen. A setup change "
            "still needs the Setup tab unlocked in your own session.",
            "A line worked by nobody but the trade being given a share has nothing to rescale, "
            "so it is skipped and named rather than guessed at.",
            "She only ever sees the project in the address bar.",
            "Check anything that matters against the tab it came from. She reads real figures, "
            "but she is a language model reading them.",
            "Every conversation is written down and goes to Drive each night as a text file, "
            "so how she is actually being used is something anybody can look at.",
        ),
        "terms": ("carmen", "staged change", "chat log", "claude opus 5", "effort",
                  "presentation deck",
                  "minuted item", "deliverable", "earned progress"),
    },
    {
        "key": "setup",
        "name": "Setup",
        "endpoints": ("projects.setup",),
        "what": "What the project is made of: sections, deliverables, weights, trades, the workflow, teams and holidays.",
        "start_here": "It starts locked. Unlock it with the setup password, change what you need, and press Save all.",
        "steps": (
            "Add <strong>sections</strong>, then the <strong>deliverables</strong> under them.",
            "Give each deliverable a <strong>weight</strong> — that is its share of the project.",
            "Set the <strong>trades</strong> and their budget hours, and allocate each deliverable "
            "across them.",
            "Set the <strong>workflow steps</strong> and the percentage each one is worth.",
            "Add the <strong>teams</strong>: which works Monday to Friday, which Sunday to Thursday, "
            "and the holidays each takes.",
            "Set each trade's <strong>office</strong> — Beirut or Cairo — and every tab that shows "
            "trades adds the figures up per office as well.",
            "Add what a minuted item may <strong>affect</strong> — the list behind Affects on the "
            "Minutes tab — rather than living with Time and Cost.",
            "<strong>Minutes template</strong>: download the form as Word, change anything in it, "
            "upload it back, and every Word export of a set of minutes is built from it.",
            "<strong>Export to Excel</strong>, edit in the sheet, and import it back.",
        ),
        "watch": (
            "Weights are relative: they do not have to add to 100, because each one's share is its "
            "points over the total.",
            "Changing a working week or a holiday moves every date planned against it.",
        ),
        "terms": ("section", "deliverable", "weight", "weighted points", "trade", "allocation",
                  "office", "workflow step", "team", "working week", "holiday", "setup password"),
    },
    {
        "key": "backups",
        "name": "Backups",
        "endpoints": ("portfolio.backups",),
        "what": "The whole database, in one file, on Google Drive, replaced every night.",
        "start_here": "Connect Google Drive once, set the hour, then check this page now and again.",
        "steps": (
            "Press <strong>Connect Google Drive</strong> and follow the three steps it prints.",
            "Set the <strong>hour and the time zone</strong> the backup should run at.",
            "Press <strong>Back up now</strong> once, to prove it works rather than assuming it.",
            "Look at <strong>What has run</strong> occasionally — that is the only place a quiet "
            "failure shows.",
        ),
        "watch": (
            "The Setup sheet's Excel export is one project's setup. It is not a backup.",
            "Only a run that actually reached Drive counts; a failed one is not a backup.",
        ),
        "terms": ("backup", "manifest", "restore", "drive.file"),
    },
    {
        "key": "portfolio",
        "name": "Portfolio",
        "endpoints": ("portfolio.index",),
        "what": "Every project you can see, side by side, at one data date.",
        "start_here": "Click a project to open it. Change the data date to read them all as at another day.",
        "steps": ("Open a project.", "Or create one, and set it up from the Setup tab."),
        "watch": ("Each card shows earned against planned, so a project slipping stands out here first.",),
        "terms": ("data date", "earned progress", "planned progress"),
    },
)

TAB_BY_KEY = {tab["key"]: tab for tab in TABS}
_BY_ENDPOINT = {endpoint: tab for tab in TABS for endpoint in tab["endpoints"]}


def for_endpoint(endpoint: str | None) -> dict[str, Any] | None:
    """The guide for the page being looked at, if there is one."""
    return _BY_ENDPOINT.get(str(endpoint or ""))


# --- what every word means --------------------------------------------------
#
# Grouped the way somebody looking one up would expect to find it, and each one
# says how it is worked out wherever the working out is the thing in doubt.

GROUPS: tuple[tuple[str, str], ...] = (
    ("progress", "Progress and earned value"),
    ("programme", "The programme"),
    ("time", "Working time"),
    ("workflow", "The design workflow"),
    ("week", "The week"),
    ("minutes", "Minutes and actions"),
    ("money", "Hours and cost"),
    ("setup", "Setup and structure"),
    ("data", "Dates, data and backups"),
)
GROUP_NAMES = dict(GROUPS)

# (term, group, what it means, how it is worked out — blank where there is
# nothing to work out.)
TERMS: tuple[tuple[str, str, str, str], ...] = (
    # --- progress and earned value
    ("Weight", "progress",
     "A deliverable's share of the project. A 6-point line is worth twice a 3-point one.",
     "weight % = this line's points ÷ every line's points. They are relative, so they need not add to 100."),
    ("Weighted points", "progress",
     "The raw number you type in Setup. Only the ratios matter.", ""),
    ("Planned progress", "progress",
     "Where the project should be at the data date, if everything ran to its dates.",
     "Σ (weight % × the line's planned %). A line's planned % steps up at each workflow date — it does "
     "not slide smoothly, because a deliverable is not 40% done because 40% of the time has passed."),
    ("Earned progress", "progress",
     "Where the project actually is. The single most useful number on the dashboard.",
     "Σ (weight % × the line's reported %)."),
    ("Actual %", "progress",
     "What one deliverable has reached, either from its workflow step or typed in directly.", ""),
    ("Variance", "progress",
     "Earned minus planned. Negative means behind.",
     "variance = earned progress − planned progress, in percentage points of the whole project."),
    ("SPI", "progress",
     "Schedule Performance Index. Below 1 is behind plan, above 1 is ahead.",
     "SPI = earned progress ÷ planned progress."),
    ("Behind plan", "progress",
     "A deliverable whose reported % is below its planned % at the data date. Not the same as late.", ""),
    ("Late", "progress",
     "A deliverable past the date it was due and not finished.",
     "Its submission date, or — once it has been submitted — its Code A date, compared with the data date."),
    ("Complete", "progress", "Reported at 100%.", ""),

    # --- the programme
    ("Deliverable", "programme",
     "One line of work with a weight, dates and a trade behind it. What the whole app is organised around.", ""),
    ("Start date", "programme", "The day work on a deliverable begins.", ""),
    ("Duration", "programme",
     "How long a deliverable takes, in <em>working</em> days for the team that owns it.",
     "Counted on that team's own working week and holidays, so a five-day line spanning a weekend "
     "takes seven calendar days."),
    ("Submission date", "programme",
     "The day the package goes to the client. The deadline that matters until it is submitted.", ""),
    ("Approval date", "programme",
     "The day the Code A is due back. Once a deliverable is with the client, this is the deadline "
     "that matters instead.", ""),
    ("Dependency", "programme",
     "A rule saying one deliverable waits on another. Four kinds, each with a lag.", ""),
    ("FS", "programme",
     "Finish to start. The successor starts after the predecessor finishes — the ordinary one.",
     "earliest start = predecessor finish + 1 + lag"),
    ("SS", "programme",
     "Start to start. The successor can start once the predecessor has started.",
     "earliest start = predecessor start + lag"),
    ("FF", "programme",
     "Finish to finish. The successor cannot <em>finish</em> until the predecessor has. It moves a "
     "start without ever mentioning it, which is why the schedule says so when it does.",
     "earliest finish = predecessor finish + lag, so the start is that less the duration"),
    ("SF", "programme",
     "Start to finish. The successor cannot finish until the predecessor has started. Rare.",
     "earliest finish = predecessor start + lag"),
    ("Lag", "programme",
     "Days added to a dependency. Negative lag (lead) lets the successor overlap the predecessor.",
     "Counted in working days, like everything else."),
    ("Float", "programme",
     "How many days a deliverable can slip before it moves the end of the project. Also called slack.",
     "float = latest it could start − earliest it can start, in working days. Zero float means it is "
     "on the critical path."),
    ("Critical path", "programme",
     "The run of work that decides the finish date. Lose a day anywhere on it and the project ends "
     "a day later.",
     "Traced back from the last deliverable to finish, following the link that was actually driving "
     "each one — not merely everything with no float, which can leave gaps."),
    ("Path", "programme",
     "A route through the dependency network from something nothing waits on to something that waits "
     "on nothing. The diagram counts how many there are.", ""),
    ("Milestone", "programme",
     "A deliverable whose start and submission are the same day — a meeting, an approval, an event.", ""),
    ("Project float", "programme",
     "How many days sit between the last submission on the programme and the contract completion date.",
     "Working days between the two. Negative means the contract date has already gone."),

    # --- working time
    ("Team", "time",
     "A working calendar — the days of the week it works and the holidays it takes — given an "
     "office. A deliverable is planned against the team of the trade carrying most of it, not "
     "set line by line, so putting a trade in Cairo is what puts its share of the work on "
     "Cairo\u2019s week.",
     "A line split between offices is worked by both: it is planned on one of them, and a day "
     "off for either is flagged on the schedule."),
    ("Working week", "time",
     "Which days a team works — Monday to Friday for Beirut, Sunday to Thursday for Cairo, or "
     "anything else.", ""),
    ("Holiday", "time",
     "A day a team does not work. It can belong to one team or to everybody.", ""),
    ("Working day", "time",
     "A day the owning team actually works. Durations, lags and workflow offsets are all counted in "
     "these, so a weekend never makes a line look late.", ""),
    ("Run-up holidays", "time",
     "Days off in the week before a submission — the days the package is being pulled together, "
     "which a programme drawn in calendar days hides.",
     "The seven days ending on the submission date, on the owning team's calendar. One everybody "
     "takes is flagged more loudly than one only that team takes."),

    # --- the design workflow
    ("Workflow step", "workflow",
     "A stage a deliverable passes through, each worth a percentage. Reaching the step sets the "
     "percentage, so nobody invents a number.", ""),
    ("Code A", "workflow", "Approved. The deliverable is done.", ""),
    ("Code B", "workflow",
     "Approved with comments. It goes back for a revision, but work can carry on.", ""),
    ("Code C", "workflow",
     "Not approved. It comes back for a revision before anything else happens.", ""),
    ("Revision", "workflow",
     "A resubmission after a Code B or C. Each one records what sent it back and what the new "
     "submission date became.", ""),
    ("Revision limit", "workflow",
     "How many resubmissions the contract allows. A deliverable at the limit is flagged red.", ""),
    ("In rework", "workflow", "On revision 1 or higher and not yet approved.", ""),

    # --- the week
    ("The week", "week",
     "What the project wants of us between one end of the week and the other, compiled from the "
     "programme and both registers.",
     "Nothing is stored. Every row is a reading of a deliverable or an item that already exists, "
     "which is why changing it here changes it everywhere."),
    ("Going out", "week", "Packages due to be issued this week.", ""),
    ("Coming back", "week", "Approvals due back from the client this week.", ""),
    ("Carrying on", "week",
     "Deliverables running through the week with nothing due at either end. The half a programme "
     "never shows.",
     "Each says where it should have got to by the <em>end</em> of the week, so “carry on with "
     "it” becomes a number."),
    ("The week is worth", "week",
     "How much of the project the week is asking for.",
     "Σ (each line's shortfall × that line's weight %). Summing bare percentages would let a 0.1% "
     "line count the same as a 9% one."),
    ("Weekly meeting", "week",
     "The internal meeting for the current week, opened with one button and referenced from the week "
     "itself (WK-2026-37).", ""),

    ("Attachment", "minutes",
     "A PDF kept with a set of minutes: named at the end of the document, and compiled onto "
     "the end of the exported PDF so the client opens one file rather than three.",
     "Kept in the database rather than in a folder beside it, because the nightly backup "
     "uploads the database — an attachment in a folder is one that does not come back."),
    ("Attendance order", "minutes",
     "How the attendance table is listed in an issued set of minutes: as the roster has them, "
     "or client first, then directors, then the project manager, then everybody else.",
     "One setting for the project, on the Minutes tab. The client is recognised by the "
     "organisation on the project; the ranks by what is in somebody's job title."),
    ("Conversation", "week",
     "One thread of questions to Carmen, kept so it can be picked up again days later instead "
     "of starting from nothing.",
     "Resuming one sends the last few turns back with the question, so it costs a little more "
     "per question than a cold start and far less than explaining the background again."),

    # --- the assistant
    ("Carmen", "week",
     "The project assistant: a language model given the run of one project. She reads anything "
     "the tabs show, proposes changes to any of it, minutes a meeting from what you type, and "
     "takes you to a page when you ask her to.",
     "She reaches every tab, the setup sheet included: settings, trades and their offices, "
     "sections, workflow steps, teams and holidays, the deliverable list, the trade split, the "
     "timesheet and both registers. She runs on Claude Opus 5 and works through the same "
     "functions the screens do — so she can do what you can do and nothing more."),
    ("Staged change", "week",
     "Something the assistant proposes rather than does. It is listed under its answer, and "
     "nothing happens until you press Apply.",
     "A model can be confidently wrong about which deliverable a phrase meant. Staging makes "
     "that a sentence to correct instead of a programme to unpick."),
    ("Chat log", "week",
     "Every question put to Carmen and every answer she gave, written down.",
     "Uploaded to Drive once a night as a plain text file, one per day, so how much she is "
     "used — and what for — is readable without this program."),
    ("Claude Opus 5", "week",
     "The model Carmen runs on, from Anthropic. One API key serves the whole installation — "
     "set it once and everybody on it is using it, so it is an administrator's to set.",
     "The key is kept in a file beside the database, never in it: the nightly backup uploads "
     "the database."),
    ("Effort", "week",
     "How hard Carmen thinks before answering — low, medium, high, xhigh or max.",
     "“high” is the default. Lower is quicker and cheaper; “max” is for when being right "
     "matters more than what it costs."),
    ("Presentation deck", "week",
     "A PowerPoint of the work done between two dates: where the project stands, what moved, "
     "what is late, the critical path, what comes next, and what is open with the client.",
     "Built from the same period report the Period tab draws, so the deck and the screen can "
     "never say different things."),

    # --- minutes and actions
    ("Minuted item", "minutes",
     "One thing raised in a meeting: what was discussed, what was agreed, who owns it, by when. Open "
     "until it is closed.", ""),
    ("Owner", "minutes",
     "The party responsible — PM, Client, MR, ST, GE, WE, EL, PMC — not a named person. People come "
     "and go from a project; the responsibility stays where it is.", ""),
    ("Impact", "minutes",
     "What an item bears on: nothing, time, cost, or both. It is what the register is filtered by "
     "when somebody asks what is threatening the programme.", ""),
    ("Open", "minutes", "Raised and not yet done.", ""),
    ("Closed", "minutes",
     "Done, on a stated day. The closing date is editable, because it is what an As-at reading "
     "turns on — not the day somebody got round to ticking it.", ""),
    ("Overdue", "minutes", "Open, with an action date already past.", ""),
    ("As at", "minutes",
     "The register as it stood on a chosen day: items raised by then, each open or closed as it was.",
     "Read off the raised and closed dates the register already keeps, so there is no separate "
     "history to be trusted."),
    ("Agenda", "minutes",
     "Everything still open, grouped by owner — the sheet you walk into the next meeting with.", ""),
    ("Attendee", "minutes",
     "Somebody on the project's attendance list. Added once, then ticked present on each meeting.", ""),
    ("Internal register", "minutes",
     "Our own action list. The same record as the client's minutes, kept for a different audience; "
     "the two never show each other's items.", ""),

    # --- hours and cost
    ("Budget hours", "money", "The hours allowed for a trade.", ""),
    ("Booked hours", "money",
     "Hours actually recorded on the Timesheet. Hours booked without a trade still count against the "
     "project total.", ""),
    ("Earned hours", "money",
     "The hours the progress made was worth.",
     "earned hours = budget hours × the trade's earned %."),
    ("CPI", "money",
     "Cost Performance Index. Below 1 means hours are going faster than progress is being earned.",
     "CPI = earned hours ÷ booked hours."),
    ("EAC", "money",
     "Estimate at completion: what the project costs in hours if it carries on at this rate.",
     "EAC = budget hours ÷ CPI."),
    ("Man-month", "money",
     "The hours one person works in a month, set per project in Setup. What turns an hours figure "
     "into something a programme can be staffed from.", ""),
    ("Trade", "money",
     "A discipline — Marine, Geotechnical, Structures, Utilities. Carries a budget, and every "
     "deliverable is allocated across one or more.", ""),
    ("Allocation", "money",
     "What share of a deliverable belongs to each trade. It is how a line's progress becomes a "
     "trade's progress.", ""),
    ("Office", "money",
     "Which of the firm's offices carries a trade — Beirut or Cairo — set against the trade on "
     "Setup. A deliverable is worked by whichever offices its trades belong to, in the same "
     "proportions, so a line split 60/40 between a Beirut trade and a Cairo one counts as both.",
     "An office's progress = the earned progress of its trades ÷ the scope weight they carry."),

    ("Target margin", "money",
     "The share of every trade's budget held back rather than planned against. Set on Setup; "
     "12% means the resource plan is drawn to 88% of the budget.", ""),
    ("Ceiling hours", "money",
     "What a trade may actually be planned to spend, and what each deliverable may take of it.",
     "A trade's ceiling = its budget hours × (1 − the target margin). A deliverable's share of "
     "that ceiling = the deliverable's weight × the trade's share of it, against the same for "
     "every other deliverable the trade carries."),
    ("Planned hours", "money",
     "The ceiling spread over the weeks the work actually runs. Hours rise towards each "
     "submission rather than sitting flat, and nothing after the submission earns any.",
     "Part of each week's share follows the workflow's value curve and the rest is flat across "
     "the working days, so the profile rises without asking for sixty percent of the work in "
     "the last five days."),
    ("Engineers per week", "money",
     "A week's planned hours as a number of people. Counted trade by trade and added up, not "
     "worked out once from the week's total: three trades each wanting four tenths of a person "
     "is three people, because they are three different people. The figure starts where the "
     "arithmetic puts it and can be typed over — the hours the week is allowed do not move.",
     "A trade's engineers = its hours that week ÷ the hours one engineer works in a week, "
     "rounded up. The week's = the sum of its trades'."),
    ("Hours per week", "money",
     "The hours one engineer works in a week, set on Setup. A billing month and a rota week "
     "are set by different people for different reasons, so this is its own number rather than "
     "the man-month divided by four.", ""),
    ("Comments reserve", "money",
     "The share of a workflow deliverable's ceiling held back at the start for answering the "
     "client's comments. Set on Setup; 15% to begin with. Only workflow lines carry one — a "
     "transmittal has no review to answer.",
     "A line's reserve = its ceiling hours × the comments reserve. Only the rest is spread "
     "over the weeks."),
    ("Released hours", "money",
     "A reserve the work never needed, because the deliverable came back Code A first time. "
     "This is the saving, and the only thing redistribution has to give away. A line that came "
     "back Code B or C spent its reserve instead: answering comments is what it was for.", ""),
    ("Redistribution", "money",
     "Putting a trade's released hours back into that trade's own open deliverables, in "
     "proportion to what each is already carrying. Never across trades, and never into a line "
     "already finalised. The notes on the Resources tab say which finished lines paid for it.",
     "Each open line gains released hours × (its planned hours ÷ that trade's open planned "
     "hours)."),
    ("Peak week", "money",
     "The week the plan wants the most people. What the resourcing conversation is actually "
     "about, because it is the week the office has to find them for.", ""),

    ("Squeeze", "programme",
     "Fitting a run of deliverables — from one line to another along the dependencies — "
     "between two dates. Every duration in the run changes by the same proportion, and "
     "whatever waits on the run moves with it. A later date extends rather than compresses.",
     "New duration = its current duration × (the new span ÷ the span it takes now), in whole "
     "days, where a span runs to the last Code A because that is when the work is finished. "
     "The leftover day goes to the shortest lines. Nothing falls below one day; a line ticked "
     "out keeps its length; and waiting between lines — a review, a curing time — is not work, "
     "so it does not compress."),
    ("Recurring meetings", "programme",
     "A numbered run of the same meeting — “Bi-weekly progress meeting No. 1”, “No. 2” — "
     "recognised by its name, its length and its cadence. There are as many of them as the "
     "programme is long, so a squeeze can add or drop them.",
     "The cadence is kept and the ones at the end are the ones added or dropped, because "
     "renumbering from the middle would rename every set of minutes already written."),
    ("Put it back", "programme",
     "Where every date stood before a squeeze. Restoring returns the dates as they actually "
     "were, rather than running the same arithmetic backwards — which does not return where "
     "it started once anything has rounded.", ""),

    # --- setup and structure
    ("Section", "setup",
     "A group of deliverables — the natural reading order of the scope.", ""),
    ("Setup password", "setup",
     "The Setup sheet starts locked on every visit, so the structure of the project cannot be "
     "changed by a stray click. Unlock it, make the change, and it re-locks itself.", ""),
    ("Save all", "setup",
     "Saves every row on the Setup sheet at once, rather than a row at a time.", ""),

    # --- dates, data and backups
    ("Data date", "data",
     "The day the project is being read as at. Everything on the page — planned progress, what is "
     "late, the S-curve — is worked out at this date, so a report can be reproduced later.", ""),
    ("NTP", "data", "Notice to proceed: the day the project starts. Month 0.", ""),
    ("Elapsed months", "data",
     "How far into the programme the data date is.",
     "(data date − NTP) ÷ days per month, with the project's own elapsed-time convention applied."),
    ("dd/mm/yyyy", "data",
     "Every date in the app is typed and shown this way, whatever the machine's locale is set to — "
     "a date field that means one thing on one computer and another on the next is a bug waiting "
     "to happen.", ""),
    ("Backup", "data",
     "The whole database — every project, everything in it — in one zip on Google Drive, replaced "
     "every night rather than added to.",
     "Taken with SQLite's own online backup, so the app carries on serving and the copy always opens."),
    ("Manifest", "data",
     "The plain-text note inside every backup saying when it was taken, which projects are in it and "
     "how many rows of each thing — so a file off the shelf can be checked before it is restored "
     "over anything.", ""),
    ("Restore", "data",
     "Putting a backup back. A command rather than a button: it discards everything since the backup "
     "was taken, and it keeps the database it replaced beside the new one.",
     "python run.py restore project-control-backup.zip"),
    ("drive.file", "data",
     "The Google Drive permission the app asks for — the narrowest one that works. It can see the "
     "files it created itself and nothing else in your Drive.", ""),
    ("Pulse", "data",
     "How a page notices somebody else changed something. It asks every few seconds and redraws "
     "itself, so two people are never looking at different numbers.", ""),
)

TERM_LOOKUP = {term.lower(): (term, group, says, how) for term, group, says, how in TERMS}


def grouped(search: str = "") -> list[dict[str, Any]]:
    """The glossary under its headings, narrowed to a search if there is one."""
    needle = " ".join(str(search or "").lower().split())
    held: dict[str, list[dict[str, str]]] = {key: [] for key, _name in GROUPS}

    for term, group, says, how in TERMS:
        if needle and needle not in f"{term} {says} {how}".lower():
            continue
        held.setdefault(group, []).append({"term": term, "says": says, "how": how})

    return [{"key": key, "name": name, "terms": held[key]}
            for key, name in GROUPS if held.get(key)]


def terms_for(tab: dict[str, Any] | None) -> list[dict[str, str]]:
    """The definitions worth having to hand on one tab, in the order named."""
    if not tab:
        return []
    found = []
    for key in tab.get("terms", ()):
        entry = TERM_LOOKUP.get(str(key).lower())
        if entry:
            found.append({"term": entry[0], "says": entry[2], "how": entry[3]})
    return found


def count() -> int:
    return len(TERMS)
