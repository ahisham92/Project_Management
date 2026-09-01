"""Loads the demo project (converted from the Sibline Port control workbook)
and creates a starting account. Safe to run more than once: it skips work
already done."""

from __future__ import annotations

import json
import os
from pathlib import Path

from datetime import datetime, timedelta

from .auth import hash_password
from .db import connect, database_path, init_db
from .workflow import default_steps

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "sibline-port.json"


def seed(database: str | None = None, seed_file: Path | None = None, quiet: bool = False) -> None:
    path = database or str(database_path())
    init_db(path)
    conn = connect(path)

    def say(message: str) -> None:
        if not quiet:
            print(message)

    try:
        email = os.environ.get("SEED_EMAIL", "admin@example.com")
        password = os.environ.get("SEED_PASSWORD", "changeme123")
        name = os.environ.get("SEED_NAME", "Project Manager")

        user = conn.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
        if user is None:
            cursor = conn.execute(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (email, name, hash_password(password), "admin"),
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            say(f"Created account {email} (password: {password})")
        else:
            say(f"Account {email} already exists — leaving it alone")

        data = json.loads((seed_file or SEED_FILE).read_text(encoding="utf-8"))
        project = data["project"]

        if conn.execute("SELECT 1 FROM projects WHERE code = ?", (project["code"],)).fetchone():
            say(f"Project {project['code']} already seeded — nothing to do")
            return

        with conn:
            project_id = conn.execute(
                """
                INSERT INTO projects (code, name, client, description, ntp_date, duration_months,
                                      days_per_month, hours_per_month, elapsed_day_offset, status, owner_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project["code"], project["name"], project["client"], project["description"],
                    project["ntp_date"], project["duration_months"], project["days_per_month"],
                    project["hours_per_month"], project.get("elapsed_day_offset", 0),
                    project.get("status", "active"), user["id"],
                ),
            ).lastrowid

            for step in default_steps():
                conn.execute(
                    """
                    INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, step["key"], step["name"], step["percent"],
                     step["anchor"], step["offset_days"], step["sort_order"]),
                )

            trade_ids = {}
            for trade in data["trades"]:
                trade_ids[trade["key"]] = conn.execute(
                    "INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, trade["key"], trade["name"], trade["budget_hours"], trade["color"], trade["sort_order"]),
                ).lastrowid

            section_ids = {}
            for section in data["sections"]:
                section_ids[section["code"]] = conn.execute(
                    "INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)",
                    (project_id, section["code"], section["name"], section["sort_order"]),
                ).lastrowid

            # The workbook holds the schedule as elapsed months since NTP; the app
            # works in real dates, so convert on the way in.
            ntp = datetime.strptime(project["ntp_date"][:10], "%Y-%m-%d").date()
            per_month = float(project["days_per_month"])

            def as_date(months: float) -> str:
                return (ntp + timedelta(days=float(months) * per_month)).isoformat()

            for task in data["tasks"]:
                start_date = as_date(task["start_month"])
                submission_date = as_date(task["finish_month"])
                # Meetings and milestones are not design submissions, so they do
                # not follow the workflow: they are tracked pro rata by time with
                # a percentage you type. The workbook marks them itself.
                is_milestone = (
                    task["finish_month"] <= task["start_month"]
                    or "(milestone)" in task["name"].lower()
                )
                tracking = "simple" if is_milestone else "workflow"

                task_id = conn.execute(
                    """
                    INSERT INTO tasks (project_id, section_id, wbs, name, weight_points,
                                       start_date, submission_date, tracking, actual_pct, remarks, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, section_ids.get(task["section_code"]), task["wbs"], task["name"],
                        task["weight_points"], start_date, submission_date, tracking,
                        task["actual_pct"], task["remarks"], task["sort_order"],
                    ),
                ).lastrowid

                for key, share in task["allocations"].items():
                    if share > 0:
                        conn.execute(
                            "INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)",
                            (task_id, trade_ids[key], share),
                        )

                if task["actual_pct"] > 0:
                    conn.execute(
                        """
                        INSERT INTO progress_updates
                            (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
                        VALUES (?, ?, ?, 0, ?, 'Imported from control workbook', ?)
                        """,
                        (task_id, project_id, user["id"], task["actual_pct"], project["ntp_date"]),
                    )

        say(
            f'Seeded "{project["name"]}" with {len(data["tasks"])} deliverables '
            f'across {len(data["sections"])} sections and {len(data["trades"])} trades.'
        )
    finally:
        conn.close()
