# Project Control

A web platform for running projects the way the Sibline Port control workbook does it:
deliverables carry **weights**, progress is reported against a **planned curve**, and
**hours booked** are measured against the budget those hours are earning.

It replaces the spreadsheet with something several people can use at once, from anywhere,
across a whole **portfolio** of projects.

**Python only.** No Node.js, no npm, no build step, and nothing to compile. The database
is SQLite, which is part of Python itself. The only two packages it needs are Flask and
Waitress.

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
| **Progress** | The full WBS. Report a new % complete on any deliverable; every update is kept as history. |
| **Schedule** | What is **late**, what is **due soon**, and what is **behind plan** but not yet late. |
| **Budget** | Hours booked vs budget vs *earned* per trade, with CPI, forecast at completion and variance at completion. |
| **Period** | What moved between two dates, and which trades earned it. |
| **Timesheet** | Book hours against a trade and optionally a deliverable. Feeds budget control directly. |
| **Setup** | Deliverables, weights, schedule months, trade splits, sections, and who can see the project. |

### How progress is measured

These are the workbook's own rules, implemented in `app/calc.py`:

```
weight %         = weight points / total weight points        (always totals 100%)
elapsed months   = (data date - NTP) / days per month
planned %        = linear ramp between a line's start and finish month
                   (finish <= start makes it a milestone: 0% -> 100% on its date)
earned progress  = weight % x actual % complete
variance         = earned - planned
```

Weights are entered as **points**, not percentages, so adding a line dilutes the others
instead of pushing the total past 100%.

Each deliverable is split across **trades** (disciplines). A trade's percent complete is
measured against its own share of the scope, which is what drives budget control:

```
earned hours = trade budget x trade % complete
CPI          = earned hours / hours booked
forecast     = budget / CPI          variance at completion = budget - forecast
```

### One deliberate difference from the source workbook

The workbook states that "month 0 = NTP", but its elapsed-time cell computes
`data date - NTP + 1`, so it credits a day of elapsed time on the NTP date itself. The two
conventions give different **planned** percentages (1.76% vs 1.38% at the 2026-09-01 cut-off).

Rather than silently pick one, this is a per-project setting under **Setup → Elapsed time
convention**. New projects default to "month 0 = NTP", which is consistent with the
schedule columns and with the late/due day counts. **The seeded Sibline Port project is set
to the workbook's convention, so its figures match your existing reports exactly.**
Earned progress is unaffected either way.

---

## Adding your own projects

1. **New project** on the portfolio page — set the code, client, NTP date and duration.
2. Add the **trades** that carry the budget, in hours. (15 man-months at 176 h/month = 2,640 h.)
3. In **Setup**, add **sections** (your scope headings), then the **deliverables** under
   each one with their weight points and start/finish months.
4. Set each deliverable's **trade split** — it must total 100%.
5. Report progress on the **Progress** tab and book hours on the **Timesheet** tab.

The Sibline Port project is loaded from `seed/sibline-port.json`, which was converted from
the control workbook — use it as a worked example of the shape of the data.

---

## Sharing it with your team

The app already handles several people; it just needs to run somewhere they can all reach.

**On your own machine, for people on the same network.** `python run.py` already listens on
every interface, so colleagues can open `http://<your-computer's-IP>:8000`. This only works
while your machine is on and on the same network, and the traffic is not encrypted — fine
for a trusted office network, not for anything sensitive.

**On a server, reachable anywhere.** Any host that runs Python or a container works —
a small VPS, Render, Railway, Fly.io, or an internal server. Three things matter:

1. **Set `SECRET_KEY`.** Without it a key is generated and stored in the data directory,
   which is fine for one machine but not for a deployment.
   Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
2. **Give it a persistent disk** and point `DATA_DIR` at it, or the database is lost
   whenever the container is replaced.
3. **Put it behind HTTPS** (a reverse proxy such as Caddy or nginx, or the host's own TLS)
   and set `HTTPS_ONLY=true` so the session cookie is marked `Secure`.

With Docker:

```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  docker compose up -d --build
docker compose exec app python run.py seed     # first run only
```

Or without Docker, on any server with Python: `pip install -r requirements.txt` then
`python run.py` behind your proxy. Waitress (the bundled server) is production-grade, so
no extra web server process is needed.

Once your team has accounts, set `ALLOW_SIGNUP=false` so strangers cannot register.

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
| `SEED_EMAIL` / `SEED_PASSWORD` / `SEED_NAME` | Used by `python run.py seed`. |

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

41 tests: the calculation engine against the workbook's published figures, and the web
layer (sign-in, every page, reporting progress, booking hours, trade splits, and the
permission rules).

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
