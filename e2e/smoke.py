"""End-to-end smoke test: signs in, reads the dashboard, records progress, books
hours, and checks both themes and the mobile layout.

    pip install playwright && python -m playwright install chromium
    python run.py seed && python run.py          # in one terminal
    python e2e/smoke.py                          # in another

Run it against a freshly seeded database — it books hours, so repeated runs
against the same database accumulate them and the budget check will fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
EMAIL = os.environ.get("SEED_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("SEED_PASSWORD", "changeme123")
SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "e2e/screenshots")

failures: list[str] = []


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    launch = {"executable_path": os.environ["CHROMIUM_PATH"]} if os.environ.get("CHROMIUM_PATH") else {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda m: failures.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: failures.append(f"pageerror: {e}"))

        def step(name: str, fn) -> None:
            try:
                fn(page)
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001 - the report is the point
                print(f"  FAIL  {name}: {exc}")
                failures.append(f"{name}: {exc}")

        def shot(name: str) -> None:
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

        step("login page renders", lambda p: (
            p.goto(f"{BASE}/login", wait_until="networkidle"),
            p.wait_for_selector("text=Project Control"),
            shot("01-login"),
        ))

        step("rejects a bad password", lambda p: (
            p.fill("input[name=email]", EMAIL),
            p.fill("input[name=password]", "totallywrong"),
            p.click("button[type=submit]"),
            p.wait_for_selector("text=Incorrect email or password", timeout=5000),
        ))

        step("signs in", lambda p: (
            p.fill("input[name=email]", EMAIL),
            p.fill("input[name=password]", PASSWORD),
            p.click("button[type=submit]"),
            p.wait_for_selector("text=Portfolio", timeout=8000),
            p.wait_for_selector("text=SIBLINE-PORT"),
            shot("02-portfolio"),
        ))

        step("portfolio shows the project and its status", lambda p: _expect_all(
            p, ["Sibline Port", "1 late", "Hours booked"]
        ))

        step("dashboard draws the S-curve with both series", _dashboard)
        step("trade table lists all four trades", lambda p: _expect_all(
            p, ["Marine", "Geotechnical", "Marine Structures", "Utilities"]
        ))
        step("chart tooltip appears on hover", _hover_tooltip)
        step("progress page lists deliverables", _progress_page)
        step("records a progress update", _record_progress)
        step("filters to late deliverables", _filter_late)
        step("schedule page splits late / due soon / behind", _schedule)
        step("budget page renders the hours chart", _budget)
        step("books hours and they reach budget control", _book_hours)
        step("period report shows what moved", _period)
        step("setup page loads the editable deliverable list", _setup)
        step("dark mode renders", _dark)
        step("mobile layout does not overflow horizontally", _mobile)

        browser.close()

    print("\n" + ("ERRORS:" if failures else "No errors."))
    for failure in failures:
        print("  -", failure)
    return 1 if failures else 0


def _expect_all(page, needles: list[str]) -> None:
    body = page.text_content("body")
    missing = [n for n in needles if n not in body]
    if missing:
        raise AssertionError(f"missing {missing}")


def _dashboard(page) -> None:
    page.click("text=Sibline Port")
    page.wait_for_selector("text=Progress S-curve", timeout=8000)
    page.wait_for_selector(".chart svg", timeout=8000)
    lines = page.locator(".chart polyline").count()
    if lines < 2:
        raise AssertionError(f"expected planned and earned lines, found {lines}")
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "03-dashboard.png"), full_page=True)


def _hover_tooltip(page) -> None:
    page.locator(".chart .hit").nth(20).hover()
    page.wait_for_selector(".chart-tip:not([hidden])", timeout=4000)
    text = page.text_content(".chart-tip")
    if "Planned" not in text:
        raise AssertionError(f"tooltip did not show a series: {text!r}")


def _progress_page(page) -> None:
    page.click("a:has-text('Progress')")
    page.wait_for_selector("text=Progress update", timeout=8000)
    page.wait_for_selector("text=Marine Design")
    page.screenshot(path=str(SHOTS / "04-progress.png"), full_page=True)


def _record_progress(page) -> None:
    row = page.locator("tr", has_text="Coastal numerical modelling").first
    row.locator("a:has-text('Update')").click()
    page.wait_for_selector("input[name=actual_pct]", timeout=8000)
    page.fill("input[name=actual_pct]", "35")
    page.click("button:has-text('Save')")
    page.wait_for_selector("text=updated to 35%", timeout=8000)
    text = page.locator("tr", has_text="Coastal numerical modelling").first.text_content()
    if "35%" not in text:
        raise AssertionError(f"progress did not persist: {text[:120]}")


def _filter_late(page) -> None:
    page.click("a:has-text('Late')")
    page.wait_for_timeout(400)
    if "kick-off" not in page.text_content("body"):
        raise AssertionError("expected the late kick-off milestone")
    page.click("a:has-text('All')")
    page.wait_for_timeout(300)


def _schedule(page) -> None:
    page.click("a:has-text('Schedule')")
    page.wait_for_selector("text=Late deliverables", timeout=8000)
    page.wait_for_selector("text=Behind plan")
    page.screenshot(path=str(SHOTS / "05-schedule.png"), full_page=True)


def _budget(page) -> None:
    page.click("a:has-text('Budget')")
    page.wait_for_selector("text=Budget control", timeout=8000)
    page.wait_for_selector(".chart svg", timeout=8000)
    page.screenshot(path=str(SHOTS / "06-budget.png"), full_page=True)


def _book_hours(page) -> None:
    page.click("a:has-text('Timesheet')")
    page.wait_for_selector("text=Book hours", timeout=8000)
    page.select_option("select[name=trade_id]", label="Geotechnical")
    page.fill("input[name=hours]", "36")
    page.fill("input[name=description]", "Borehole data review")
    page.click("button:has-text('Book hours')")
    page.wait_for_selector("text=Booked 36 hours", timeout=8000)
    if "Borehole data review" not in page.text_content("body"):
        raise AssertionError("entry not listed")
    page.screenshot(path=str(SHOTS / "07-timesheet.png"), full_page=True)

    page.click("a:has-text('Budget')")
    page.wait_for_selector("text=Budget control", timeout=8000)
    if "36 h" not in page.text_content("body"):
        raise AssertionError("booked hours did not reach budget control")


def _period(page) -> None:
    page.click("a:has-text('Period')")
    page.wait_for_selector("text=Period report", timeout=8000)
    page.wait_for_selector("text=Earned in period by trade")
    page.screenshot(path=str(SHOTS / "08-period.png"), full_page=True)


def _setup(page) -> None:
    page.click("a:has-text('Setup')")
    page.wait_for_selector("text=Project setup", timeout=8000)
    page.wait_for_selector("text=Deliverables")
    page.screenshot(path=str(SHOTS / "09-setup.png"), full_page=True)


def _dark(page) -> None:
    page.click("a:has-text('Dashboard')")
    page.wait_for_selector("text=Progress S-curve", timeout=8000)
    page.evaluate("localStorage.setItem('pm-theme','dark');document.documentElement.setAttribute('data-theme','dark')")
    page.wait_for_timeout(500)
    page.screenshot(path=str(SHOTS / "10-dashboard-dark.png"), full_page=True)


def _mobile(page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(600)
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    if overflow > 2:
        raise AssertionError(f"page scrolls horizontally by {overflow}px")
    page.screenshot(path=str(SHOTS / "11-mobile.png"), full_page=True)


if __name__ == "__main__":
    raise SystemExit(main())
