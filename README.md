# Project Control

A web platform for running projects the way the Sibline Port control workbook does it:
deliverables carry **weights**, progress is reported against a **planned curve**, and
**hours booked** are measured against the budget those hours are earning.

It replaces the spreadsheet with something multiple people can use at once, from anywhere,
across a whole **portfolio** of projects.

---

## What it does

| Screen | What it answers |
|---|---|
| **Portfolio** | Across every project I manage: how far ahead or behind am I, what is late, how many hours have I burned? |
| **Dashboard** | For one project: earned vs planned progress, the S-curve, progress and budget by trade, what needs attention. |
| **Progress** | The full WBS. Report a new % complete on any deliverable; every update is kept as history. |
| **Schedule** | What is **late**, what is **due soon**, and what is **behind plan** but not yet late. |
| **Budget** | Hours booked vs budget vs *earned* per trade, with CPI, forecast at completion and variance at completion. |
| **Timesheet** | Book hours against a trade and optionally a deliverable. Feeds budget control directly. |
| **Setup** | Deliverables, weights, schedule months, trade splits, sections, and who can see the project. |

### How progress is measured

These are the workbook's own rules, implemented in `server/src/calc.js`:

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

## Running it locally

```bash
npm run install:all     # install server and client dependencies
npm run seed            # create the first account + load the Sibline Port project
npm run build           # build the client
npm start               # http://localhost:4000
```

Sign in with `admin@example.com` / `changeme123` and change the password from the app.

For development with hot reload, run the two halves in separate terminals:

```bash
npm run dev:server      # API on :4000
npm run dev:client      # UI on :5173, proxying /api to :4000
```

Run the calculation tests (they check the engine against the workbook's published figures):

```bash
npm test
```

---

## Deploying it so it is reachable anywhere

The app is a single Node process that serves both the API and the built UI, with a SQLite
database on disk. Any host that runs a container and gives you a persistent volume works.

**Always set `JWT_SECRET`** — the server refuses to start in production without it:

```bash
node -e "console.log(require('crypto').randomBytes(48).toString('hex'))"
```

### Docker (any VPS)

```bash
JWT_SECRET=$(node -e "console.log(require('crypto').randomBytes(48).toString('hex'))") \
  docker compose up -d --build
docker compose exec app npm --prefix server run seed   # first run only
```

Put it behind a reverse proxy with TLS (Caddy or nginx). The session cookie is set with
`Secure` in production, so **the app must be served over HTTPS** or sign-in will not stick.

### Render / Railway / Fly.io

1. Point the service at this repository; the `Dockerfile` is picked up automatically.
2. Set `JWT_SECRET`, and `NODE_ENV=production`.
3. Attach a persistent disk mounted at `/data` (Render: *Disks*; Fly: `fly volumes create`).
   Without one, the database is lost whenever the container is replaced.
4. On first deploy, run `npm --prefix server run seed` once in a shell on the instance to
   create your account — or just register in the browser: **the first account created
   becomes the administrator**.
5. Set `ALLOW_SIGNUP=false` afterwards so only you can add people.

### Environment variables

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | **Required in production.** Signs session tokens. |
| `PORT` | Listen port (default `4000`; most hosts set this). |
| `DATA_DIR` | Directory holding `pm.sqlite` (default `server/data`). Point at a volume. |
| `DATABASE_FILE` | Full path to the database file, if you'd rather set it directly. |
| `ALLOW_SIGNUP` | `false` blocks self-registration. The first account is always allowed. |
| `SEED_EMAIL` / `SEED_PASSWORD` / `SEED_NAME` | Used by `npm run seed` for the first account. |

---

## Adding your own projects

1. **New project** on the portfolio page — set the code, client, NTP date and duration.
2. Add the **trades** that carry the budget, in hours. (15 man-months at 176 h/month = 2,640 h.)
3. In **Setup**, add **sections** (your scope headings), then the **deliverables** under
   each one with their weight points and start/finish months.
4. Set each deliverable's **trade split** — it must total 100%.
5. Report progress on the **Progress** tab and book hours on the **Timesheet** tab.

The Sibline Port project is loaded from `server/seed/sibline-port.json`, which was
converted from the control workbook — use it as a worked example of the shape of the data.

---

## Access model

- Accounts are email + password; passwords are stored as bcrypt hashes.
- Sessions are httpOnly cookies, so tokens are not reachable from page scripts.
- The **first** account to register becomes an administrator and can see every project.
- Everyone else sees only projects they own or have been added to.
- Per-project roles: **owner** (everything, including deleting the project), **manager**
  (edit setup and team), **member** (report progress, book hours), **viewer** (read only).

---

## Layout

```
server/
  src/calc.js         progress, schedule and earned-value maths (no I/O — directly testable)
  src/schema.sql      database schema
  src/service.js      loading and roll-up helpers
  src/routes/         auth, projects, tasks, users
  seed/               the Sibline Port project as JSON
  test/calc.test.js   checks the engine against the workbook's figures
client/
  src/pages/          portfolio, dashboard, progress, schedule, budget, timesheet, setup
  src/components/     shared UI and charts
```

---

## End-to-end check

`e2e/smoke.mjs` drives a real browser through sign-in, the dashboard, a progress update,
booking hours, both themes and the mobile layout:

```bash
npm install playwright && npx playwright install chromium
npm --prefix server run seed && npm run build && npm start   # in one terminal
node e2e/smoke.mjs                                           # in another
```

Run it against a freshly seeded database — it books hours, so repeated runs against the
same database accumulate them.
