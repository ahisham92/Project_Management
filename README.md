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
| **Schedule** | What is **late**, what is **due soon** (any window, or **all dates**), and what is **behind plan** but not yet late. Shows every workflow date per line: IDC, comments, submission, Code A. |
| **Budget** | Hours booked vs budget vs *earned* per trade, with CPI, forecast at completion and variance at completion. |
| **Period** | What moved between two dates, and which trades earned it. |
| **Timesheet** | Book hours against a trade and optionally a deliverable. Feeds budget control directly. |
| **Setup** | Deliverables, weights, dates, trade splits, sections, the design workflow, revision rules, and who can see the project. **Locked** by default, and round-trips to **Excel**. |

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

Every date reads and is typed as **dd/mm/yyyy** — 1 September is `01/09/2026`. The fields are
plain text rather than the browser's date picker, because a native picker follows the
machine's locale, which is why 1 September could show as `09/01`. Typing is forgiving:
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

**Progress**, **Schedule**, **Budget** and **Period** each carry a **Print / PDF** button. It
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
| **Render** | `render.yaml` | *New → Blueprint*, point it at this repo. A disk needs a paid instance. |
| **Fly.io** | `fly.toml` | `fly launch --no-deploy --copy-config`, then `fly volumes create project_data --size 1`, then `fly deploy`. Listens on 8080. |
| **Railway / Heroku-like** | `Procfile` | Attach a volume and set `DATA_DIR` to it. |
| **Any server or VPS** | `Dockerfile`, `docker-compose.yml` | `SECRET_KEY=… docker compose up -d --build` |

Free tiers change often; check the current terms before relying on one. What does not change
is the requirement for a persistent disk.

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
commands work from anywhere**. Check the name and the region it was created in first:

```bash
flyctl apps list                       # the app name
flyctl status -a project-management    # the region it actually runs in
```

```bash
# 1. The volume that holds the database. It must be in the SAME region as the app.
flyctl volumes create project_data --size 1 --region cdg -a project-management

# 2. The key that signs sign-ins. Without it everyone is signed out on restart.
flyctl secrets set SECRET_KEY=<a long random string> -a project-management
```

On Windows PowerShell, generating that key without needing Python on your PATH:

```powershell
$key = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
flyctl secrets set SECRET_KEY=$key -a project-management
```

On macOS or Linux: `flyctl secrets set SECRET_KEY=$(openssl rand -hex 32) -a project-management`.

If the first deploy fails saying the volume `project_data` was not found, that is why — create
it and deploy again. If it complains the app name is taken, change the `app = ` line at the
top of `fly.toml`, since Fly app names are unique across all of Fly.

**If Fly pushes a `flyio-new-files` branch**, check the `fly.toml` on it before deploying from
it. Fly regenerates the file and has been seen to set `internal_port = 8080` while leaving
`PORT = "8000"` — traffic is then routed to a port nothing is listening on and the app is
simply unreachable, with no error to explain it. The two must be the same number. Everything
here is set to **8080**, which is what Fly assumes, so the regenerated file lines up. The
`test_every_config_agrees_on_the_port_the_app_listens_on` test checks this on every push.

The simplest course is to take the `fly.toml` from your own branch rather than Fly's: it is
the same configuration with the ports consistent, comments intact, and the volume mounted.

Then create the first account:

```bash
flyctl ssh console -C "python run.py seed" -a project-management
```

Your address is `https://<app-name>.fly.dev`. Put that in the `APP_URL` line of
`docs/index.html` and the GitHub Pages front door links straight into it.

After the first deploy, create the starting account once — on Render use its Shell, on Fly
`fly ssh console`, on your own server just run it:

```bash
python run.py seed          # creates admin@example.com / changeme123 and the demo project
```

Sign in, change that password, then set `ALLOW_SIGNUP=false` so strangers cannot register
and add your colleagues from **Setup → Team**.

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

115 tests: the calculation engine (the workflow step dates, the stepped planned figure,
resubmissions and the revision cap, and the workbook's own weights, earned progress and
per-trade man-months), the web layer (sign-in, every page, reporting progress by status,
raising revisions, booking hours, the dd/mm/yyyy dates, the setup lock and the permission
rules), sorting, Save all, the print output, the Excel round trip, and what hosting needs —
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
