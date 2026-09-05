# Project Control

A web platform for running projects the way the Sibline Port control workbook does it:
deliverables carry **weights**, progress is reported against a **planned curve**, and
**hours booked** are measured against the budget those hours are earning.

It replaces the spreadsheet with something several people can use at once, from anywhere,
across a whole **portfolio** of projects.

**Python only.** No Node.js, no npm, no build step, and nothing to compile. The database
is SQLite, which is part of Python itself. It needs three packages: Flask, Waitress and
openpyxl (for the Excel round trip).

---

## Installing it on your computer

You need Python 3.10 or newer. Check with `python3 --version` (Windows: `py --version`).
If you don't have it, get it from [python.org/downloads](https://www.python.org/downloads/) —
on Windows, tick **"Add Python to PATH"** in the installer.

Then, in a terminal, from the folder containing this file:

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python run.py seed      # creates your first account and loads the demo project
python run.py --open    # starts the app and opens it in your browser
```

**Windows (PowerShell or Command Prompt)**

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

py run.py seed
py run.py --open
```

The app runs at **http://localhost:8000**. Sign in with `admin@example.com` /
`changeme123`, then change the password from the account page (click your name, top right).

To stop it, press `Ctrl+C`. To start it again later, activate the environment
(`source .venv/bin/activate` or `.venv\Scripts\activate`) and run `python run.py`.

The `venv` step is optional but recommended — it keeps these two packages out of your
system Python. Without it, `pip install -r requirements.txt` still works.

### Everything `run.py` can do

| Command | What it does |
|---|---|
| `python run.py` | Start the server (add `--open` to launch a browser, `--port 9000` to change the port) |
| `python run.py seed` | Create the first account and load the Sibline Port demo project |
| `python run.py create-user` | Add another account, prompting for the details |
| `python run.py init-db` | Create an empty database with no demo data |

Your data lives in one file: **`data/pm.sqlite`**. Copy it to back the whole system up.

---

## What it does

| Screen | What it answers |
|---|---|
| **Portfolio** | Across every project I manage: how far ahead or behind am I, what is late, how many hours have I burned? |
| **Dashboard** | For one project: earned vs planned progress, the S-curve, progress and budget by trade, what needs attention. |
| **Progress** | The full WBS. Move a deliverable to its next **status** — the status sets the percentage. Record client comments to raise a **revision**. Every update is kept as history. |
| **Schedule** | The programme: every deliverable in WBS order with its **start, duration and finish**, a **Gantt** of the whole thing, **dependencies** and the **critical path**. Dates are amended here, and the whole programme round-trips to **Excel**. |
| **Budget** | Hours booked vs budget vs *earned* per trade, with CPI, forecast at completion and variance at completion. |
| **Period** | What moved between two dates, and which trades earned it. |
| **Timesheet** | Book hours against a trade and optionally a deliverable. Feeds budget control directly. |
| **Minutes** | Minutes of meeting: attendance ticked per meeting, what was agreed, who owns it, whether it bears on **time or cost**, open or closed. Filter, search, and export to **Word** or PDF. |
| **Setup** | Deliverables, weights, trade splits, sections, the design workflow, revision rules, **teams with their working weeks and holidays**, and who can see the project. Dates are amended on the Schedule. **Locked** by default, and round-trips to **Excel**. |

### Minutes of meeting

The **Minutes** tab keeps the meeting record and the action register in one place.

- **Attendance list** — people are added once, with their organisation, role and trade.
  Every later meeting shows them as tick boxes: invited, and present. Whoever is not ticked
  present appears as apologies on the minutes.
- **A meeting** carries its reference, subject, date, time, location, who chaired it and when
  the next one is. Adding one invites everyone currently on the list.
- **An item** carries the subject, the discussion, **what was agreed**, its **owner**, its
  **trades**, whether it **affects time or cost** (or both, or neither), its action date, and
  whether it is **open or closed**. Closing one stamps the date it closed. What was agreed
  and what was discussed are full writing boxes, so a long agreement can be read back
  before it is saved.
- **The owner is a party, not a person**: PM, Client, MR, ST, GE, WE, EL or PMC. People move
  on and off a project while the responsibility stays where it is, and the minutes read the
  same however the team changes.
- **An item can sit with several trades at once** — tick as many as it bears on. It then
  answers a filter on any one of them.
- **Item numbers are positions, not typing.** The first item in MOM-04 is 4.1, the second
  4.2, and so on. Two items cannot share a number, and the ▲ ▼ buttons on the meeting page
  swap an item with its neighbour and renumber both. Deleting an item closes the gap;
  moving one to another meeting renumbers the meeting it left and the one it joined;
  renaming MOM-04 to MOM-07 renumbers its items to 7.1, 7.2, ...
- **The short fields are changed by clicking them.** Owner, trades, what an item affects
  and its action date are edited in the row: click the value, change it, and it saves on
  the spot — no page reload, and nothing else on the item is touched. The status badge
  follows the date it now carries.
- **Edit is for the writing.** It opens the subject, the agreement and the discussion under
  the item, without reloading the page or losing your position in the list.
- With JavaScript switched off both are ordinary links that open the item's full form on
  the server, and each control has its own Save button.
- **Filters**: open, overdue, affects time, affects cost, closed, or everything — combined
  with a keyword search across the subject, discussion, agreement, owner and meeting, and
  with filters by **owner**, **trade**, **meeting** and a **date range**. Every column sorts.
- **Next-meeting agenda** — every item still open, grouped by who owns it. That is the sheet
  to walk into the next meeting with.

Each of those three screens exports to **Word** (`.docx`) and prints to PDF, and each carries
the project number and name at the top. The Word file is written by `app/word.py` using the
standard library alone, so nothing extra has to be installed for it.

### The programme

The **Schedule** tab is the plan, not a reading of progress — late and behind plan sit on
Progress and the Dashboard, where they belong.

- **Every deliverable, in WBS order**, with its start, its duration in calendar days and its
  finish. A switch at the top says which way round you enter them: **start + duration**, and
  the finish follows; or **start and finish**, and the duration follows. Click any of the
  three and change it in the row.
- **The whole programme exports to Excel and imports back.** The workbook is one Schedule
  sheet — WBS, deliverable, start, duration, finish and section — with the column the plan
  works out for itself shaded, so it is clear which two of the three to fill in. Edit the
  dates in Excel, import it, and every deliverable named by WBS is moved to what the sheet
  says; anything that pushes work later takes its dependants with it. A row naming a WBS
  that is not in the project is reported rather than silently dropped.
- **The Gantt.** A band of months across the top says where in the programme you are looking.
  A bar per line runs from start to submission with progress shown inside it, and the
  **submission** itself is a green star. A line on the design workflow also carries its
  **IDC** as a red circle and its **Code A** as a red star; a line tracked as a plain
  percentage — a meeting, a milestone, a transmittal — has neither, because neither happens
  to it. Today is a dashed vertical line, and a legend names every mark. **Hover any row** —
  the bar or the WBS number beside it — and it says what the line is: its full name, its
  section, its dates, its duration, its float, how far it has got, and whether anything is
  holding its start back.
- **The charts come first, the tables fold away underneath.** Each chart carries a *For
  details click here* toggle that opens the table below it. Your browser remembers which you
  left open, a form always brings its own panel back open when it saves, and everything is
  opened for printing whatever state it was left in.
- **Rework.** A submission comes back as **Code A** (approved), **Code B** or **Code C**.
  B and C raise a revision, and each resubmission draws its own amber bar underneath the
  line, running from the day the comments landed to the new date and labelled with the code
  that caused it — so rework shows on the programme at the size it actually cost.
- **Dependencies**, in all four kinds — **finish → start**, **start → start**,
  **finish → finish** and **start → finish**. Each takes a lag in days, and the lag **may be
  negative**: "start a week before the survey ends" is finish → start with a lag of -7, which
  is how overlap between two pieces of work is written down. The lag and the kind are both
  changed by clicking them in the row, and so are **both ends of the link** — the deliverable
  and what it waits for — so a link put on the wrong line is moved where it belongs instead
  of being removed and made again. Move a line and everything that depends on it is
  pushed out with it — only ever later, since bringing work forward frees float rather than
  dragging the programme back. A link that would make the programme depend on itself, one
  onto a pair already linked, or one onto a deliverable from another project, is refused
  with the reason said in place — the row goes back to what it was and nothing is lost.
- The dependencies **export to Excel and import back**. Deliverables are named by WBS, the
  workbook lists them on a second sheet to copy from, and importing replaces the lot with
  what the sheet says. A row naming a WBS that does not exist, or one that would make the
  programme loop, is reported rather than silently dropped.
- **The critical path** is worked out properly: a forward pass for the earliest each line
  could run, a backward pass for the latest it could run without moving the finish, and the
  difference is its float. A line with none is critical. A line with no links at all is not
  on a path, so it is not called critical until it is sequenced.
- **The network** below the plan draws who waits for whom as boxes laid out in the order the
  work runs. A box is a WBS number — hover it for the deliverable, its dates and its float —
  so a long programme stays readable. A link leaves the left-hand edge of a box when it waits
  on that line's *start* and the right-hand edge when it waits on its *finish*, and a
  start-to-start link is drawn dashed. The critical run is red. **Drag any box** to move it
  and the arrows follow; it stays where you put it.
- **The diagram is where links are made and unmade.** Drag from the small plug on a box's
  right edge onto another box and that line now waits for this one; click a line and it is
  gone. Both land where they stand — the dates, the float, the bars, the tiles and the count
  of paths all follow without the page reloading.
- **Click a deliverable** and it opens in a panel beside the plan: its start, its duration in
  working days, its submission, its team, its float, its status, anything holding its start
  back, and both sides of its dependencies — what it waits for and what waits on it. Every
  one of those is editable in the panel, and a change there is a change on the schedule. The
  link behind it is a real link to the deliverable's own page, so it works with JavaScript
  off too.
- **Simplify** untangles the picture once the links are all in. It lays the diagram out in
  layers — columns stay exactly as they are, since they say the order the work runs in — and
  sweeps up and down them putting each box at the median of what it joins in the column
  beside it, keeping the best arrangement it finds. A link that skips columns gets a stand-in
  box in each one it passes, so a long line sailing over the picture is counted properly
  rather than as crossing nothing. It reports what it managed: *"Simplified — crossing lines
  down from 9 to 0."* The result is written down as the boxes' positions, so you can nudge
  one by hand from there, and **Tidy up** forgets the lot and returns to the automatic
  layout.
- **The end of every path is blue**, and the diagram says how many unique paths run through
  it — a route being a run from a line nothing precedes to a line nothing waits on. The
  count is worked out along the topological order rather than by walking every route, so a
  large network costs one pass.
- A line that **cannot start where it is drawn** says so, and says why: the hint names the
  link holding it back and does the arithmetic out loud — *"1.2 finishes on 30/09/2026.
  Finish → finish with a lag of 40 days puts this line's finish at 09/11/2026, and at 16
  days long that means starting on 25/10/2026."* Finish → finish and start → finish are the
  two that surprise people: they fix the finish, never mentioning the start, but a line of a
  fixed length can only meet a later finish by starting later.

### Teams, working weeks and holidays

A programme drawn in calendar days says a deliverable ran over a weekend nobody worked, and
then reads as behind on the Monday. **Setup → Teams and their working days** fixes that.

- A **team** is a working week plus its holidays. **Monday to Friday**, **Sunday to
  Thursday**, Monday to Saturday and every day are offered by name; any other week is set day
  by day with the seven tick boxes.
- A **holiday** belongs to one team or to everybody. Each deliverable names the team it is
  planned against — from the Setup sheet, from the Team column on the Schedule, or from its
  own panel — and anything not given one follows the project's default team.
- **Durations, lags and the workflow step offsets are counted in that team's working days.**
  Five days from a Monday finishes on the Friday for Beirut and on the following Sunday for
  Cairo, and a holiday in the middle pushes both out by a day.
- **A date that lands on a day off is moved to the next day the team is in.** A start on a
  public holiday is not a start, and nothing is submitted on a day nobody is working.
- **Planned progress runs on working days too**, so a line does not read as behind on a
  Monday morning because the plan moved on over a weekend the team was not there.
- **Holidays in the week before a submission are flagged** on the schedule, on the
  deliverable's panel, and counted in a tile of their own — with whose holiday it is, because
  a day everybody is off is worth knowing about earlier than one only one team takes.

Every project starts with a single **Every day** team, so nothing moves until somebody says a
team keeps a shorter week. Assigning a team keeps a line's dates and re-reads its duration in
the days that team actually works — a 30-day span becomes 22 working days, and it is that
number the next edit works in.

### Nothing needs refreshing

Everything you change saves where you change it and redraws in place: a status, a percentage,
a date, a duration, an owner, a trade. Nothing reloads the page.

Each project page also checks the server every fifteen seconds for a short token that moves
whenever anything on the project changes, and quietly redraws itself when it does — so two
people working at once see each other's edits. The check pauses while the tab is in the
background, and while anything is being edited, so nobody's typing is ever pulled out from
under them. The counter behind it is kept by triggers inside the database, which is what
makes it exact: no write can forget to move it, and two changes in the same second cannot be
mistaken for one.

### How progress is measured

Every deliverable has a **start date** and a **submission date** (type either the date or a
number of days from NTP — the form takes both). Progress is reported by moving the line
through the **design workflow**:

| Status | Worth | Planned |
|---|---|---|
| Design started | 10% | on the start date |
| IDC provided | 40% | 5 days **before** submission |
| Comments addressed | 60% | 2 days **before** submission |
| Submitted to client | 80% | on the submission date |
| Code A received | 100% | 14 days **after** submission |

**Every number in that table is editable** on the Setup sheet — the percentages, whether a
step hangs off the start or the submission date, and the day offset. You can add and remove
steps too.

A submission cycle moves in **steps**, not smoothly, and the planned figure follows: it reads
the percentage of the **last step whose date has passed**. So a workflow line's planned
progress only ever shows 0, 10, 40, 60, 80 or 100 — never a value in between. It sits at 40%
from the IDC date until the comments date, then jumps to 60%.

Lines that are not design submissions — meetings, milestones — are tracked as a **simple
percentage** you type, **pro rata by time** between the two dates, or stepping 0% → 100% on
the date when both are the same. The seeded project sets the meetings this way automatically,
from the "(milestone)" marker the workbook already carries. You can switch any line between
the two on the Setup sheet.

```
weight %         = weight points / total weight points        (always totals 100%)
earned progress  = weight % x actual % complete
variance         = earned - planned
```

Weights are entered as **points**, not percentages, so adding a line dilutes the others
instead of pushing the total past 100%.

### Resubmissions

A deliverable that is submitted but does not come back with a Code A is not simply "late" —
it goes round again. On the Progress tab, **Comments** on a submitted line records that:

- the **revision** goes up by one (Rev 1, Rev 2, …);
- the line drops back to the step you nominate (default **Comments addressed**, 60%), so
  earned progress falls to reflect the rework, and the drop shows in the period report;
- a **new submission date** is set — either the one you type, or the comments date plus the
  project's **rework days** (default 7);
- every downstream planned date moves with it, so the schedule and the S-curve follow;
- the cycle is written to the deliverable's **history**, with the outcome of each revision.

Once submitted, a line is judged on its **Code A date** rather than its submission date, so
work sitting with the client is not reported as late until the approval is actually overdue.

A project has a **maximum revisions** setting (default 10). A deliverable that reaches it is
flagged for escalation on the schedule and cannot be pushed further without raising the
limit — so a line stuck at Rev 10 is visible rather than quietly cycling.

### Sorting

The progress and schedule tables sort on any column — WBS, deliverable, section, weight,
dates, planned, actual, variance, status, revision. Click a heading to sort, click it again
to reverse. WBS sorts naturally, so 1.9 comes before 1.10.

On the progress tab, sorting by anything other than WBS folds the sections away into one
ranked list — which is what you want when the question is "what is furthest behind?" Sorting
by WBS brings the sections back.

### Dates

Every date reads and is typed as **dd/mm/yyyy** — 1 September is `01/09/2026`. Clicking a
date field opens a **calendar** to pick from; it is drawn by the app itself rather than being
the browser's own picker, because a native one follows the machine's locale, which is why
1 September could show as `09/01`. Whatever is picked is written back as dd/mm/yyyy on every
machine. The field is still an ordinary text box, so typing works too, and it is forgiving:
`01/09/2026`, `1/9/26`, `01-09-2026` and `2026-09-01` are all understood.

Each deliverable is split across **trades** (disciplines). A trade's percent complete is
measured against its own share of the scope, which is what drives budget control:

```
earned hours = trade budget x trade % complete
CPI          = earned hours / hours booked
forecast     = budget / CPI          variance at completion = budget - forecast
```

### The setup sheet is locked

Setup holds the basis of every figure in the project, so the whole page is **read-only until
you unlock it**. The starting password is **2026**, and it can be changed on the page itself.

This is a guard against accidental edits, the way a protected spreadsheet is — not a security
boundary. Anyone with manager access to the project can be given the password; what really
controls who can change a project is the **role** (see Access model below).

### Saving the setup

The whole Setup sheet is one form: project settings, the workflow, trades, sections and every
deliverable, including each line's trade split. **Save all changes** in the bar at the foot of
the page writes the lot in a single transaction. If any trade split does not total 100%, the
save is rejected and nothing at all is written, so the sheet can never end up half saved.

### Setup ↔ Excel

**Export to Excel** writes the whole setup to one workbook: project settings, the workflow,
trades, sections, and every deliverable with its weight, dates and trade split. Edit it in
Excel and **Import from Excel** brings it back.

- Deliverables are matched on **WBS**, so a line keeps its identity, its history and its
  booked hours across a round trip. A row deleted from the workbook is deleted from the
  project.
- **Status and Revision are exported for reference but never read back.** Progress belongs to
  the app; importing a workbook exported last week must not revert what was reported since.
- The file is checked in full before anything is written — a trade split that does not total
  100%, or a row with no date, is rejected and the project is left exactly as it was.

### How planned progress relates to the source workbook

The original control workbook derived planned progress from a linear ramp over *elapsed
months*. This app derives it from the workflow's *step dates*, which is a different — and for
design submissions, more truthful — model: at the 2026-09-01 cut-off the seeded project reads
2.03% planned rather than the workbook's 1.76%. Earned progress, the weights and the per-trade
figures are unchanged.

The workbook's elapsed-time quirk (it measures `data date - NTP + 1`, contradicting its own
"month 0 = NTP" note) now only affects the headline "months elapsed" figure. It remains a
per-project setting under **Setup → Elapsed time convention**.

### Printing and PDF for management

**Progress**, **Schedule**, **Budget**, **Period** and **Minutes** each carry a **Print / PDF**
button. It
opens your browser's print dialog, where "Save as PDF" is a destination on every current
browser — so there is no PDF library to install and nothing to keep up to date.

The printed page is not a screenshot of the screen: navigation, filters, buttons and the sort
arrows are dropped; the dark theme reverts to ink on white; a report header carries the project,
its code, the client, the report name and the data date; long tables break across pages without
splitting a row and repeat their headings on each page. A4 landscape is the default.

---

## Adding your own projects

1. **New project** on the portfolio page — set the code, client, NTP date and duration.
2. Add the **trades** that carry the budget, in hours. (15 man-months at 176 h/month = 2,640 h.)
3. **Unlock** the Setup sheet with the setup password (**2026** to begin with).
4. Add **sections** (your scope headings), then the **deliverables** under each one with
   their weight points and their start and submission dates.
5. Check the **design workflow** — the five steps and their offsets — and adjust it to how
   your submissions actually run.
6. Set each deliverable's **trade split** — it must total 100%.
7. Report progress on the **Progress** tab and book hours on the **Timesheet** tab.

For a large scope, step 4 is far quicker in Excel: **Export to Excel**, fill in the
Deliverables sheet, and **Import from Excel**.

The Sibline Port project is loaded from `seed/sibline-port.json`, which was converted from
the control workbook — use it as a worked example of the shape of the data.

---

## Putting it online for the team

### Why GitHub Pages cannot host it

GitHub Pages serves **static files only** — HTML, CSS and images. Project Control is a Python
application with a shared database behind it, so there is nothing on Pages to run the code or
to store everyone's progress updates together. A `github.io` address can only ever be a front
door to the real thing.

That front door is included: `docs/index.html` is published to
**https://ahisham92.github.io/Project_Management/** by the *Landing page* workflow. Until you
give it an address it explains how to get the app running; once you paste the address into the
single `APP_URL` line at the top of that file, it becomes a button straight into the live app.

To turn Pages on: repository **Settings → Pages → Source: GitHub Actions**.

### Where it does run

Anything that executes Python and can keep a file between restarts. Three things matter
wherever you choose:

1. **A persistent disk.** The whole database is one SQLite file. Point `DATA_DIR` at a disk
   that survives restarts, or every deploy starts from an empty database.
2. **`SECRET_KEY` set on the host.** Without it a key is generated and kept in the data
   directory; if that directory is ephemeral, everyone is signed out on every restart.
   Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
3. **HTTPS, with `HTTPS_ONLY=true`.** The session cookie is then marked `Secure`. Most hosts
   terminate TLS for you; on your own server put Caddy or nginx in front.

The repository ships the configuration for the common options, so there is little to write:

| Host | File | Notes |
|---|---|---|
| **PythonAnywhere** | `wsgi.py` | Free tier runs Flask with a persistent filesystem. Walkthrough below. |
| **Render** | `render.yaml` | *New → Blueprint*, point it at this repo. A disk needs a paid instance. |
| **Fly.io** | `fly.toml` | `fly launch --no-deploy --copy-config`, then `fly volumes create project_data --size 1`, then `fly deploy`. Listens on 8080. |
| **Railway / Heroku-like** | `Procfile` | Attach a volume and set `DATA_DIR` to it. |
| **Any server or VPS** | `Dockerfile`, `docker-compose.yml` | `SECRET_KEY=… docker compose up -d --build` |

Free tiers change often; check the current terms before relying on one. What does not change
is the requirement for a persistent disk.

### PythonAnywhere

The free "Beginner" plan runs a Flask app on a filesystem that persists, at
`https://<username>.pythonanywhere.com` with HTTPS included — which is the whole requirement
for this app. PythonAnywhere serves the app itself through `wsgi.py`, so `run.py` and Waitress
are not used there.

**1. In a Bash console on PythonAnywhere** — Consoles tab → **Bash**. This runs on
PythonAnywhere's own Linux server, in your browser. These are not commands for your own PC:
running them there installs nothing on the server, and `.venv/bin/pip` does not exist on
Windows anyway (it is `.venv\Scripts\pip` there).

```bash
cd ~
git clone https://github.com/ahisham92/Project_Management.git
cd Project_Management
python3.13 -m venv .venv          # match the Python version set on the Web tab
.venv/bin/pip install -r requirements.txt
mkdir -p ~/project-data
```

Use the same Python version here as the one selected for the web app, or the virtualenv is
ignored. The repository's default branch already holds the application, so a plain `git clone`
checks out the right code.

**2. Create the web app.** Click **Web** in the top menu bar, then the **Add a new web app**
button on the left. A short wizard appears:

| Screen | What to do |
|---|---|
| *Your web app's domain name* | Just click **Next**. On the free plan the only option is `<username>.pythonanywhere.com`. |
| *Select a Python Web framework* | Choose **Manual configuration** — it is the last entry in the list, below Django, web2py, Flask and Bottle. **Do not choose Flask.** |
| *Select a Python version* | Pick the same 3.x version your virtualenv was built with (`.venv/bin/python --version` in the console tells you). |

Choosing **Flask** generates a brand-new hello-world app under `~/mysite` and wires the site to
that instead of to this one. **Manual configuration** creates the site without generating any
code, and leaves the WSGI file for you to point at `wsgi.py`, which is what step 4 does.

**If you already created the web app with the Flask option**, there is no need to delete it and
start again: the only difference is what the WSGI file was pre-filled with, and step 4 replaces
that file entirely. Set the virtualenv, replace the WSGI file, reload. The unused `~/mysite`
folder can be left alone or deleted.

**3. Set the Virtualenv.** Back on the Web tab, scroll to the **Virtualenv** section, click
*Enter path to a virtualenv, if desired* and type
`/home/<username>/Project_Management/.venv`, then press Enter. Leaving this blank is the most
common reason the site keeps serving the old hello-world page.

**4. Edit the WSGI configuration file** (the link is on the same page) and replace everything
in it with this, substituting your username and a long random string:

```python
import os
import sys

path = "/home/<username>/Project_Management"
if path not in sys.path:
    sys.path.insert(0, path)

# Kept outside the repository so a git pull cannot disturb it.
os.environ["DATA_DIR"] = "/home/<username>/project-data"
os.environ["SECRET_KEY"] = "<a long random string>"
os.environ["HTTPS_ONLY"] = "true"
os.environ["ALLOW_SIGNUP"] = "true"   # set to false once your team has accounts

from wsgi import application  # noqa: E402
```

**5. Tick "Force HTTPS"**, then **Reload**.

**6. Open `https://<username>.pythonanywhere.com/register`** and create your account — the
first one is the administrator. There is no need to run `seed` unless you also want the demo
project; if you do, run `.venv/bin/python run.py seed` in the console first, with
`DATA_DIR=/home/<username>/project-data` set.

Two things to know about the free plan: the web app must be **renewed every month** — log in
and press *Run until 1 month from today* on the Web tab, or the site is disabled (they email a
week before) — and you get 512 MB of disk, which is far more than this app and its database
need.

**Updating it** is a console command and a button — there is no automatic deploy on the free
plan, so `.github/workflows/deploy.yml` does nothing here:

```bash
cd ~/Project_Management && git pull && .venv/bin/pip install -r requirements.txt
```

then **Reload** on the Web tab. The database is untouched by this: it lives in
`~/project-data`, outside the repository.

#### Deploying on Fly.io, field by field

If you are using Fly's **Deploy from GitHub** page, the two path boxes are asking about paths
*inside the repository*, not on your own computer — never paste a path like
`C:\Users\you\Project_Management`.

| Field | What to put | Why |
|---|---|---|
| **Managed Postgres** | leave **unchecked** | The database is a SQLite file on the volume. Postgres would sit there unused and cost money. |
| **Working directory** | leave **blank** (`./`) | `Dockerfile` and `requirements.txt` are at the repository root. |
| **Config path** | leave **blank** (`./`) | `fly.toml` is at the repository root too. |

Two things the deploy page does not do for you, both needed before the app is usable.

`flyctl` finds the app name by reading `fly.toml` in the current directory. If you deployed
from Fly's web page you probably have no local clone, so **name the app with `-a` and the
commands work from anywhere**.

Do not assume the name and region you asked for. Fly appends a suffix when the name is taken
and may place the app in a different region — both end up written into `fly.toml`, which Fly
commits back to the repository:

```bash
flyctl apps list                       # the real app name
grep -E "^app|^primary_region" fly.toml
```

Then, substituting your own app name and its region:

```bash
# 1. The volume that holds the database. It must be in the SAME region as the app,
#    or the machine cannot mount it.
flyctl volumes create project_data --size 1 --region <region> -a <app-name>

# 2. The key that signs sign-ins. Without it everyone is signed out on restart.
flyctl secrets set SECRET_KEY=<a long random string> -a <app-name>
```

On Windows PowerShell, generating that key without needing Python on your PATH:

```powershell
$key = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
flyctl secrets set SECRET_KEY=$key -a <app-name>
```

On macOS or Linux: `flyctl secrets set SECRET_KEY=$(openssl rand -hex 32) -a <app-name>`.

If the first deploy fails saying the volume `project_data` was not found, that is why — create
it and deploy again. If it complains the app name is taken, change the `app = ` line at the
top of `fly.toml`, since Fly app names are unique across all of Fly.

**Fly rewrites `fly.toml` and commits it back**, usually through a `flyio-new-files` branch and
a pull request. It has been seen to set `internal_port` to 8080 while leaving `PORT` at 8000 —
traffic is then routed to a port nothing is listening on, and the app is unreachable with
nothing in the logs to explain it. Everything here is therefore set to **8080**, the port Fly
assumes, so a regenerated file agrees with itself. The
`test_every_config_agrees_on_the_port_the_app_listens_on` test checks all three files on every
push, so a bad rewrite fails CI rather than reaching your team.

Your address is `https://<app-name>.fly.dev`. Open `/register` there to create the first
account — see *The first account, without a shell* below. Put the address in the `APP_URL`
line of `docs/index.html` and the GitHub Pages front door links straight into it.

If `flyctl ssh console` fails with `can't build tunnel for personal: websocket: failed to
WebSocket dial`, that is Fly's private-network tunnel, not the app. `flyctl wireguard reset`
usually clears it, and a corporate network or VPN blocking the gateway is the usual cause.
Nothing above needs SSH, so it is not worth fighting unless you want a shell for its own sake.

#### When the site cannot be reached

`flyctl status`, `flyctl logs` and `flyctl volumes list` go through Fly's API rather than the
SSH tunnel, so they work even when `ssh console` does not. Three things account for most of it:

**`Trial machine stopping. To run for longer than 5m0s, add a credit card`** in the logs, and
the machine shows `stopped`. Fly's trial stops a machine after five minutes whatever
`auto_stop_machines` says. A shared team app has to stay up, so this needs a card on the
account — no amount of configuration will get around it.

**`Health check 'servicecheck-00-http-8080' ... has failed`** together with a startup line
reading `running at http://localhost:8000`. The running image predates the port alignment:
Fly probes 8080 while the app listens on 8000, so the proxy never routes traffic and the site
looks dead. Redeploy so the current config is used, and check the logs then say
`running at http://localhost:8080`.

**More than one volume with the same name.** `flyctl volumes list` shows the region of each
and which machine it is attached to. Only the attached one holds your data; the others are
empty and still cost money. Destroy them with
`flyctl volumes destroy <id> -a <app-name>`, and make sure `primary_region` matches the region
of the volume that is attached — otherwise a later deploy can start a second machine on an
empty volume, and you end up with two databases that quietly disagree.

### The first account, without a shell

You do not need to run anything on the server. **The first account to register becomes the
administrator**, and registration is open while the database has no users at all — even with
`ALLOW_SIGNUP=false`. So:

1. Open `https://<your-app>/register`.
2. Create your own account. It is created as the administrator.
3. Set `ALLOW_SIGNUP=false` on the host so nobody else can register.
4. Add colleagues from **Setup → Team** (they register first, you give them a role).

`python run.py seed` is the alternative, and is only worth a shell if you want the demo
Sibline Port project on the live instance as well as an account. Use it on Render's Shell, or
`flyctl ssh console -C "python run.py seed" -a <app-name>`.

### Moving a project onto the live app

If you have been using it locally, do not rebuild the scope by hand:

1. On your own machine: **Setup → Export to Excel**.
2. On the live app: **New project** with the same code and NTP date, leaving the trades blank.
3. **Setup → Unlock**, then **Import from Excel** with that workbook.

Deliverables, weights, dates, trade splits, sections and the workflow all come across. Progress
does not — status and revision are exported for reference only — so report the current status
on the live instance once, and it is then the single copy everyone works from.

Without Docker on your own server: `pip install -r requirements.txt` then `python run.py`.
Waitress, the bundled server, is production-grade — there is no second web server to run.

### Keeping the live app up to date

`.github/workflows/tests.yml` runs the whole test suite on every push and then checks that the
app actually starts and answers `/healthz`.

`.github/workflows/deploy.yml` redeploys the running app on every push to the branch, so what
your team uses always matches the code. It does nothing until you add the secret for your
host, so it is harmless to leave in place:

- **Render** — *Settings → Deploy Hook*, then add it as the repository secret
  `RENDER_DEPLOY_HOOK`. (Render's own `autoDeploy` in `render.yaml` already does this; the
  hook is there for the case where you turn that off.)
- **Fly.io** — `fly tokens create deploy`, then add it as the secret `FLY_API_TOKEN`.

Data changes need no deployment at all: everyone is reading and writing the same database, so
a progress update is visible to the next person who loads the page.

### Several people at once

SQLite allows one writer at a time. The app uses write-ahead logging so reads never block, and
waits up to ten seconds (`SQLITE_BUSY_TIMEOUT_MS`) for a write rather than failing — without
that wait, two people saving at the same moment get "database is locked". A test in
`tests/test_hosting.py` drives six clients writing at once to hold this honest.

That is comfortable for a team working on projects together. It is not built for hundreds of
simultaneous writers; if you ever get there, the database layer is small and isolated in
`app/db.py`.

### On your own machine, for people on the same network

`python run.py` listens on every interface, so colleagues can open
`http://<your-computer's-IP>:8000` while your machine is on and they are on the same network.
The traffic is not encrypted — fine for a trusted office network, not for anything sensitive,
and not a substitute for hosting it.

### Settings

All optional — see `.env.example`.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the session cookie. Generated and stored in `data/` if unset. |
| `PORT` | Listen port (default `8000`). |
| `DATA_DIR` | Directory holding `pm.sqlite` (default `data/`). Point at a volume when deploying. |
| `DATABASE_FILE` | Full path to the database file, if you'd rather set it directly. |
| `HTTPS_ONLY` | `true` marks the session cookie `Secure`. Set once you are serving over HTTPS. |
| `ALLOW_SIGNUP` | `false` blocks self-registration. The first account is always allowed. |
| `SQLITE_BUSY_TIMEOUT_MS` | How long a write waits for another to finish (default `10000`). |
| `SEED_EMAIL` / `SEED_PASSWORD` / `SEED_NAME` | Used by `python run.py seed`. |

The **setup password** is not an environment variable — it is stored per project and changed
on the Setup sheet itself.

---

## Access model

- Accounts are email + password; passwords are stored as salted scrypt hashes.
- Sessions are signed, httpOnly cookies, so tokens are not reachable from page scripts.
- The **first** account created becomes an administrator and can see every project.
- Everyone else sees only projects they own or have been added to. A project someone
  cannot see is reported as missing, so the app never confirms that an id exists.
- Per-project roles: **owner** (everything, including deleting the project), **manager**
  (edit setup and team), **member** (report progress, book hours), **viewer** (read only).

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

454 tests: the calculation engine (the workflow step dates, the stepped planned figure,
resubmissions and the revision cap, and the workbook's own weights, earned progress and
per-trade man-months), the programme (durations both ways round, the four link kinds with
negative lags, the forward and backward passes, float and the critical path, cascading
shifts, refused loops, why a line cannot start where it is drawn, the routes through
the network, untangling the diagram, and the schedule and dependency workbooks), working
calendars (the two working weeks, holidays for one team or all of them, durations and lags in
working days, dates moved off a day off, planned progress that does not tick over a weekend,
and the flag on a submission with a holiday in its run-up), the minutes register
(filters, search, sorting, renumbering on a move, and the Word output), the web layer
(sign-in, every page, reporting progress by status, raising revisions, booking hours, the
dd/mm/yyyy dates, the setup lock and the permission rules), sorting, Save all, the print
output, the Excel round trips, editing in the row, the live check, and what hosting needs —
the health check, six people writing at the same time, and the deployment files agreeing
with each other.

There is also a browser smoke test that drives the real app:

```bash
python -m playwright install chromium
python run.py seed && python run.py      # in one terminal
python e2e/smoke.py                      # in another
```

Run it against a freshly seeded database — it books hours, so repeated runs against the
same database accumulate them.

Its 42 steps cover both themes and the mobile layout, and each screenshot lands in
`e2e/screenshots/`. Among them: recording progress in the row, linking two deliverables and
watching what follows shift, moving either end of a link, dragging a box in the network,
taking the schedule out to Excel and importing the edited workbook back, reading a bar by
hovering it and folding the tables away under the charts, untangling the diagram with Simplify, drawing a
link by dragging between two boxes and erasing it by clicking the line, opening a deliverable
in its panel, setting up two teams with a holiday between them, and a second window picking up
a change on its own.

---

## Layout

```
run.py                  start the server, seed, create accounts
requirements.txt        the two packages the app needs
app/
  calc.py               progress, schedule and earned-value maths (no I/O — directly testable)
  schema.sql            database schema
  db.py                 SQLite access
  auth.py               passwords, sessions, per-project permissions
  service.py            loading and roll-up helpers
  charts.py             charts drawn as inline SVG on the server
  filters.py            template formatting helpers
  workflow.py           the design workflow: steps, their dates, and revision rules
  excel.py              writing and reading the setup workbook
  dates.py              dd/mm/yyyy in, ISO stored
  sorting.py            column ordering for the progress and schedule tables
  schedule.py           durations, dependencies, float and the critical path
  calendars.py          working weeks and holidays: which days a team is in
  layout.py             untangling the dependency diagram: layers and crossings
  minutes.py            minutes of meeting: filtering, sorting, open/closed and time/cost
  minutes_doc.py        the Word documents built from the minutes
  word.py               writes a .docx with the standard library — no extra package
  seed.py               loads the demo project
  views/                the pages
  templates/            Jinja2 templates
  static/               one stylesheet, one small script
seed/                   the Sibline Port project as JSON
tests/                  pytest suite
e2e/smoke.py            browser smoke test
```

Charts are generated as SVG by `app/charts.py` rather than by a JavaScript library, so the
pages need no bundler, no CDN and no internet connection, and they print correctly. The
only JavaScript is a small script for the theme toggle, chart tooltips and delete
confirmations — every page works with it switched off.
