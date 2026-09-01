PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',      -- 'admin' | 'user'
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  code             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  client           TEXT NOT NULL DEFAULT '',
  description      TEXT NOT NULL DEFAULT '',
  ntp_date         TEXT NOT NULL,                  -- YYYY-MM-DD, elapsed months are measured from here
  duration_months  REAL NOT NULL DEFAULT 12,
  days_per_month   REAL NOT NULL DEFAULT 30.4375,  -- programme basis for converting elapsed months to dates
  hours_per_month  REAL NOT NULL DEFAULT 176,      -- for showing man-month budgets as hours
  elapsed_day_offset REAL NOT NULL DEFAULT 0,      -- 0: NTP day counts as 0 elapsed; 1: NTP day counts as one day worked
  max_revisions    INTEGER NOT NULL DEFAULT 10,    -- resubmissions allowed before a deliverable is escalated
  rework_days      REAL NOT NULL DEFAULT 7,        -- comments received -> next submission, when a revision is raised
  revision_reset_step TEXT NOT NULL DEFAULT 'comments_addressed', -- the step a rejected deliverable returns to
  setup_password_hash TEXT NOT NULL DEFAULT '',    -- unlocks the setup sheet; blank means unlocked
  currency         TEXT NOT NULL DEFAULT 'USD',
  status           TEXT NOT NULL DEFAULT 'active', -- 'active' | 'on_hold' | 'complete' | 'archived'
  owner_id         INTEGER NOT NULL REFERENCES users(id),
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       TEXT NOT NULL DEFAULT 'member',       -- 'manager' | 'member' | 'viewer'
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS sections (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  code       TEXT NOT NULL DEFAULT '',
  name       TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sections_project ON sections(project_id);

CREATE TABLE IF NOT EXISTS trades (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key          TEXT NOT NULL,
  name         TEXT NOT NULL,
  budget_hours REAL NOT NULL DEFAULT 0,
  color        TEXT NOT NULL DEFAULT '#2563eb',
  sort_order   INTEGER NOT NULL DEFAULT 0,
  UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS tasks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  section_id    INTEGER REFERENCES sections(id) ON DELETE SET NULL,
  wbs           TEXT NOT NULL DEFAULT '',
  name          TEXT NOT NULL,
  weight_points REAL NOT NULL DEFAULT 0,
  start_date      TEXT NOT NULL DEFAULT '',        -- YYYY-MM-DD, when design is planned to start
  submission_date TEXT NOT NULL DEFAULT '',        -- YYYY-MM-DD, the planned submission for the current revision
  tracking      TEXT NOT NULL DEFAULT 'workflow',  -- 'workflow' (status steps) | 'simple' (a percentage you type)
  status_key    TEXT NOT NULL DEFAULT '',          -- the workflow step reached; blank means not started
  revision      INTEGER NOT NULL DEFAULT 0,        -- 0 = first issue; raised each time comments come back
  actual_pct    REAL NOT NULL DEFAULT 0,           -- 0..1, set from the status on workflow lines
  remarks       TEXT NOT NULL DEFAULT '',
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);

-- The design workflow. Each step carries the percent complete it represents and
-- when it is planned, as an offset from either the start date or the submission
-- date. Every value is editable per project.
CREATE TABLE IF NOT EXISTS workflow_steps (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  name        TEXT NOT NULL,
  percent     REAL NOT NULL DEFAULT 0,             -- 0..1
  anchor      TEXT NOT NULL DEFAULT 'submission',  -- 'start' | 'submission'
  offset_days REAL NOT NULL DEFAULT 0,             -- negative is before the anchor
  sort_order  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (project_id, key)
);
CREATE INDEX IF NOT EXISTS idx_steps_project ON workflow_steps(project_id);

-- One row per submission cycle, so the resubmission trail is visible.
CREATE TABLE IF NOT EXISTS task_revisions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  revision        INTEGER NOT NULL DEFAULT 0,
  submission_date TEXT NOT NULL DEFAULT '',        -- planned submission for this revision
  outcome         TEXT NOT NULL DEFAULT 'open',    -- 'open' | 'code_a' | 'comments'
  outcome_date    TEXT NOT NULL DEFAULT '',
  note            TEXT NOT NULL DEFAULT '',
  user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_revisions_task ON task_revisions(task_id);

CREATE TABLE IF NOT EXISTS task_allocations (
  task_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
  pct      REAL NOT NULL DEFAULT 0,                -- 0..1, must total 1 across a task
  PRIMARY KEY (task_id, trade_id)
);

CREATE TABLE IF NOT EXISTS progress_updates (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  previous_pct REAL NOT NULL DEFAULT 0,
  actual_pct   REAL NOT NULL DEFAULT 0,
  note         TEXT NOT NULL DEFAULT '',
  data_date    TEXT NOT NULL,                      -- YYYY-MM-DD the progress is reported against
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_progress_project_date ON progress_updates(project_id, data_date);
CREATE INDEX IF NOT EXISTS idx_progress_task ON progress_updates(task_id);

CREATE TABLE IF NOT EXISTS time_entries (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  trade_id    INTEGER REFERENCES trades(id) ON DELETE SET NULL,
  task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  entry_date  TEXT NOT NULL,                       -- YYYY-MM-DD
  hours       REAL NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_time_project_date ON time_entries(project_id, entry_date);
