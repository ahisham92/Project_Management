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
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
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
        step("records a progress update by status", _record_progress)
        step("raises a revision when comments come back", _raise_revision)
        step("filters to late deliverables", _filter_late)
        step("schedule page splits late / due soon / behind", _schedule)
        step("schedule shows all dates and every workflow column", _all_dates)
        step("dates read dd/mm/yyyy", _dates_read_dd_mm)
        step("budget page renders the hours chart", _budget)
        step("books hours and they reach budget control", _book_hours)
        step("period report shows what moved", _period)
        step("progress sorts by a column", _sorting)
        step("planned reads only the workflow step values", _stepped_planned)
        step("setup starts locked and opens with the password", _setup_lock)
        step("setup saves everything with one button", _save_all)
        step("setup exports to Excel", _excel_export)
        step("report tabs print to PDF", _print_to_pdf)
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
    """Progress is reported by moving a deliverable to a workflow step."""
    row = page.locator("tr", has_text="Coastal numerical modelling").first
    row.locator("a:has-text('Update')").click()
    page.wait_for_selector("select[name=status_key]", timeout=8000)
    page.select_option("select[name=status_key]", label="Submitted to client — 80%")
    page.click("button:has-text('Save')")
    page.wait_for_selector("text=updated to 80%", timeout=8000)
    text = page.locator("tr", has_text="Coastal numerical modelling").first.text_content()
    if "80%" not in text or "Submitted to client" not in text:
        raise AssertionError(f"status did not persist: {text[:160]}")


def _raise_revision(page) -> None:
    """The client returns comments instead of a Code A."""
    row = page.locator("tr", has_text="Coastal numerical modelling").first
    row.locator("a:has-text('Comments')").click()
    page.wait_for_selector("input[name=comments_date]", timeout=8000)
    page.fill("input[name=comments_date]", "05/09/2026")
    page.fill("input[name=note]", "Code B returned")
    page.click("button:has-text('Raise revision')")
    page.wait_for_selector("text=moved to revision 1", timeout=8000)
    text = page.locator("tr", has_text="Coastal numerical modelling").first.text_content()
    if "Rev 1" not in text:
        raise AssertionError(f"revision not shown: {text[:160]}")
    page.screenshot(path=str(SHOTS / "05-revision.png"), full_page=True)


def _all_dates(page) -> None:
    page.click("a:has-text('Schedule')")
    page.wait_for_selector("text=Late deliverables", timeout=8000)
    page.select_option("select[name=horizon]", "all")
    page.click("button:has-text('Apply')")
    page.wait_for_selector("text=Due in everything ahead", timeout=8000)
    body = page.text_content("body")
    for column in ("IDC", "Comments", "Submission", "Code A"):
        if column not in body:
            raise AssertionError(f"the schedule is missing the {column} column")
    page.screenshot(path=str(SHOTS / "06-schedule-all.png"), full_page=True)


def _dates_read_dd_mm(page) -> None:
    body = page.text_content("body")
    if "31/08/2026" not in body:
        raise AssertionError("dates should read dd/mm/yyyy")
    if page.locator("input[type=date]").count():
        raise AssertionError("a native date picker would follow the machine's locale")


def _sorting(page) -> None:
    page.click("a:has-text('Progress')")
    page.wait_for_selector("text=Progress update", timeout=8000)
    page.click("th a:has-text('Variance')")
    page.wait_for_selector("text=All deliverables", timeout=8000)
    first = page.locator("tbody tr").first.text_content()
    if "1.6" not in first:
        raise AssertionError(f"worst variance should sort first, got {first[:80]}")
    page.click("th a:has-text('WBS')")
    page.wait_for_selector("text=Sec. 3.1 Marine Design", timeout=8000)
    page.screenshot(path=str(SHOTS / "12-sorted.png"), full_page=True)


def _stepped_planned(page) -> None:
    """Planned should read one of the step values, never something between."""
    values = page.eval_on_selector_all(
        "table tbody tr td:nth-child(5)", "els => els.map(e => e.textContent.trim())"
    )
    seen = {v for v in values if v.endswith("%")}
    allowed = {"0%", "10%", "40%", "60%", "80%", "100%", "7%"}
    stray = seen - allowed
    if stray:
        raise AssertionError(f"planned showed values between steps: {sorted(stray)}")


def _save_all(page) -> None:
    page.fill("input[name='max_revisions']", "8")
    page.click("button:has-text('Save all changes')")
    page.wait_for_selector("text=Saved — project settings", timeout=8000)
    if page.input_value("input[name='max_revisions']") != "8":
        raise AssertionError("the saved value did not come back")


def _print_to_pdf(page) -> None:
    """Each report tab offers a print button and carries a print-only header."""
    for tab, heading in [("Progress", "Progress update"), ("Schedule", "Schedule"),
                         ("Budget", "Budget control"), ("Period", "Period report")]:
        page.click(f"a.tabs >> nth=0" if False else f"nav.tabs a:has-text('{tab}')")
        page.wait_for_selector(f"text={heading}", timeout=8000)
        if page.locator("[data-print]").count() == 0:
            raise AssertionError(f"{tab} has no print button")
        if page.locator(".print-header").count() == 0:
            raise AssertionError(f"{tab} has no print header")

    # Render the page as the printer sees it, which is how a PDF comes out.
    page.emulate_media(media="print")
    page.wait_for_timeout(400)
    hidden = page.evaluate(
        "getComputedStyle(document.querySelector('.topbar')).display === 'none'"
    )
    if not hidden:
        raise AssertionError("the navigation is still on the page when printing")
    page.screenshot(path=str(SHOTS / "13-print.png"), full_page=True)
    page.emulate_media(media="screen")


def _setup_lock(page) -> None:
    page.click("a:has-text('Setup')")
    page.wait_for_selector("text=Project setup", timeout=8000)
    if "Locked" not in page.text_content("body"):
        raise AssertionError("the setup sheet should start locked")

    page.fill("input[name=password]", "2026")
    page.click("button:has-text('Unlock')")
    page.wait_for_selector("text=Setup sheet unlocked", timeout=8000)
    body = page.text_content("body")
    for expected in ("Design workflow", "IDC provided", "Maximum revisions",
                     "Rework days", "Export to Excel", "Import from Excel"):
        if expected not in body:
            raise AssertionError(f"setup is missing {expected!r}")
    page.screenshot(path=str(SHOTS / "10-setup.png"), full_page=True)


def _excel_export(page) -> None:
    with page.expect_download(timeout=10000) as download:
        page.click("a:has-text('Export to Excel')")
    name = download.value.suggested_filename
    if not name.endswith(".xlsx"):
        raise AssertionError(f"unexpected download: {name}")


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
