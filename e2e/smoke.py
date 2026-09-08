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
import re
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
        page.on("console", lambda m: failures.append(f"console: {m.text}")
                if m.type == "error" and "400 (BAD REQUEST)" not in m.text else None)
        page.on("pageerror", lambda e: failures.append(f"pageerror: {e}"))
        # Every confirm in the app is one the test means to accept. One handler
        # for the run, rather than a `once` per step — two of those left over
        # race for the same dialog and one of them throws.
        page.on("dialog", lambda dialog: dialog.accept())

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
            p.wait_for_selector("text=Project Control >> visible=true"),
            shot("01-login"),
        ))

        step("rejects a bad password", lambda p: (
            p.fill("input[name=email]", EMAIL),
            p.fill("input[name=password]", "totallywrong"),
            p.click("button[type=submit]"),
            p.wait_for_selector("text=Incorrect email or password >> visible=true", timeout=5000),
        ))

        step("signs in", lambda p: (
            p.fill("input[name=email]", EMAIL),
            p.fill("input[name=password]", PASSWORD),
            p.click("button[type=submit]"),
            p.wait_for_selector("text=Portfolio >> visible=true", timeout=8000),
            p.wait_for_selector("text=SIBLINE-PORT >> visible=true"),
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
        step("records a progress update by status, in the row", _record_progress)
        step("raises a revision when comments come back", _raise_revision)
        step("filters to late deliverables", _filter_late)
        step("a line with the client reads as released, not as late", _with_client)
        step("schedule draws the programme with its milestones", _schedule)
        step("schedule links two deliverables and shifts what follows", _schedule_links)
        step("schedule squeezes a run into fewer days", _squeeze)
        step("schedule dates and durations are amended in the row", _schedule_amend)
        step("schedule dependencies are edited and dragged", _schedule_deps)
        step("schedule dates go out to Excel and come back", _schedule_excel)
        step("schedule reads at a glance and folds its tables away", _schedule_reading)
        step("Simplify untangles the diagram", _schedule_simplify)
        step("the critical path is traced start to end", _critical_path)
        step("a link is drawn and erased on the diagram itself", _diagram_links)
        step("a deliverable opens in a panel with its dependencies", _task_panel)
        step("teams keep their own working week and holidays", _teams)
        step("each chart prints on its own sheet", _print_one_chart)
        step("dates read dd/mm/yyyy", _dates_read_dd_mm)
        step("budget page renders the hours chart", _budget)
        step("books hours and they reach budget control", _book_hours)
        step("resources plans the hours into weeks and people", _resources)
        step("a bigger target margin leaves less to plan with", _resources_margin)
        step("a week's engineers are set by hand, live, without moving its hours",
             _resources_staffing)
        step("both resources tables sort on every column, trades included",
             _resources_sorting)
        step("a clean Code A releases its comments reserve, and it can be shared out",
             _resources_reserve)
        step("summarized progress shows what moved, on the plan and in the minutes",
             _period)
        step("minutes: adds attendees, a meeting and its items", _minutes_capture)
        step("minutes: filters, searches and sorts the register", _minutes_filters)
        step("minutes: exports a set of minutes to Word", _minutes_word)
        step("minutes: reorders items and renumbers them", _minutes_reorder)
        step("minutes: edits an item in place without reloading", _minutes_edit_in_place)
        step("minutes: changes a field by clicking it in the row", _minutes_cells)
        step("minutes: picks a date from the calendar", _minutes_calendar)
        step("minutes: the agenda lists what is still open", _minutes_agenda)
        step("minutes: a PDF on the template with an attachment compiled in", _minutes_export)
        step("minutes: an item moves where it stands, without a reload", _minutes_live_move)
        step("minutes: people move up the roster, live", _attendee_order)
        step("minutes: the layout comes off a Word template you can edit",
             _minutes_template)
        step("internal: a weekly list of its own, read as at a date", _internal_register)
        step("internal: the week compiles the programme and both registers", _this_week)
        step("a helper on every tab, and one page of definitions", _how_to_use)
        step("the dashboard overview shows dates, float, progress and earned", _overview)
        step("Carmen answers, stages a change, and applies it", _assistant)
        step("Carmen reads what you attach and hands a document back", _carmen_files)
        step("Carmen changes the setup sheet and shares a trade across every line",
             _assistant_changes_the_setup)
        step("a presentation downloads as a PowerPoint", _deck)
        step("Carmen is on every page, minutes a meeting and takes you places",
             _carmen_everywhere)
        step("progress sorts by a column", _sorting)
        step("planned reads only the workflow step values", _stepped_planned)
        step("setup starts locked and opens with the password", _setup_lock)
        step("setup saves everything with one button", _save_all)
        step("setup exports to Excel", _excel_export)
        step("report tabs print to PDF", _print_to_pdf)
        step("dark mode renders", _dark)
        step("a change appears on another page without a refresh", _live)
        step("backups: the page says where things stand", _backups)
        step("mobile layout does not overflow horizontally", _mobile)

        browser.close()

    print("\n" + ("ERRORS:" if failures else "No errors."))
    for failure in failures:
        print("  -", failure)
    return 1 if failures else 0


def _schedule_page(page, panel: str = ""):
    """The schedule, with the folded panel a step needs already open."""
    page.goto(f"{BASE}/projects/1/schedule" + (f"?panel={panel}" if panel else ""),
              wait_until="networkidle")
    _put_carmen_away(page)


def _open_carmen(page) -> None:
    """Opens the pop-up. It starts shut on every page, and the launcher hides
    itself while it is open."""
    if not page.locator("#carmen-popup:not([hidden])").count():
        page.click("#carmen-open")
    page.wait_for_selector("#carmen-popup:not([hidden])", timeout=6000)


def _put_carmen_away(page) -> None:
    """Shuts the pop-up if a previous step left it open.

    It is fixed in the corner, so anything it covers belongs to it and not to
    the page underneath — which is true for a person as much as for a test.
    """
    if page.locator("#carmen-popup:not([hidden])").count():
        page.click("[data-carmen-close]")
        page.wait_for_timeout(200)


def _card(page, heading: str):
    """The card under a heading — several of them carry an Export button now."""
    return page.locator("div.card").filter(has=page.locator(f"h2:text-is('{heading}')"))


def _expect_all(page, needles: list[str]) -> None:
    body = page.text_content("body")
    missing = [n for n in needles if n not in body]
    if missing:
        raise AssertionError(f"missing {missing}")


def _dashboard(page) -> None:
    page.click("text=Sibline Port >> visible=true")
    page.wait_for_selector("text=Progress S-curve >> visible=true", timeout=8000)
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
    page.wait_for_selector("text=Progress update >> visible=true", timeout=8000)
    page.wait_for_selector("text=Marine Design >> visible=true")
    page.screenshot(path=str(SHOTS / "04-progress.png"), full_page=True)


def _record_progress(page) -> None:
    """Progress is reported by clicking the row and choosing a workflow step."""
    row = page.locator("tr", has_text="Coastal numerical modelling").first
    before = page.url
    row.locator(".cell-open[data-cell]").first.click()
    page.wait_for_selector("form.cell-form select[name=status_key]", timeout=8000)
    page.select_option("form.cell-form select[name=status_key]", label="Submitted to client — 80%")
    page.wait_for_timeout(1200)

    if page.url != before:
        raise AssertionError("reporting progress should not reload the page")
    text = page.locator("tr", has_text="Coastal numerical modelling").first.text_content()
    if "80%" not in text or "Submitted to client" not in text:
        raise AssertionError(f"status did not persist: {text[:160]}")


def _raise_revision(page) -> None:
    """The client returns comments instead of a Code A."""
    row = page.locator("tr", has_text="Coastal numerical modelling").first
    row.locator("a:has-text('Code B / C')").click()
    page.wait_for_selector("input[name=comments_date]", timeout=8000)
    page.select_option("select[name=code]", "C")
    page.fill("input[name=comments_date]", "05/09/2026")
    page.fill("input[name=note]", "Not approved")
    page.click("button:has-text('Raise revision')")
    page.wait_for_selector("text=Code C >> visible=true", timeout=8000)
    text = page.locator("tr", has_text="Coastal numerical modelling").first.text_content()
    if "Rev 1" not in text:
        raise AssertionError(f"revision not shown: {text[:160]}")
    page.screenshot(path=str(SHOTS / "05-revision.png"), full_page=True)


def _schedule_excel(page) -> None:
    """The dates and durations download, survive an edit in Excel, and import."""
    from openpyxl import load_workbook

    _schedule_page(page, "dates")
    card = _card(page, "Dates and durations")
    with page.expect_download(timeout=10000) as download:
        card.locator("a:has-text('Export to Excel')").click()
    workbook = str(SHOTS / "schedule.xlsx")
    download.value.save_as(workbook)
    if not download.value.suggested_filename.endswith(".xlsx"):
        raise AssertionError("the schedule did not download as a workbook")

    sheet = load_workbook(workbook)["Schedule"]
    wbs = str(sheet.cell(row=2, column=1).value)
    if not wbs or wbs[0].isalpha():
        raise AssertionError(f"the first data row should be a WBS number, got {wbs!r}")

    # Edit it the way anyone would: stretch the first deliverable by a fortnight.
    was = int(sheet.cell(row=2, column=4).value)
    sheet.cell(row=2, column=4).value = was + 14
    sheet.parent.save(workbook)

    card.locator("input[name=workbook]").set_input_files(workbook)
    card.locator("button:has-text('Import')").click()
    page.wait_for_selector("text=rescheduled >> visible=true", timeout=8000)
    if "skipped" in page.text_content("body"):
        raise AssertionError("its own export should import without a complaint")

    row = _card(page, "Dates and durations").locator("tbody tr").first
    if f"{was + 14}d" not in row.inner_text():
        raise AssertionError(f"the table still reads {was}d, not the imported {was + 14}d")
    page.screenshot(path=str(SHOTS / "24-schedule-excel.png"), full_page=True)


def _schedule_reading(page) -> None:
    """The page opens on its charts; a bar says what it is; the diagram marks
    where each path ends and says how many there are."""
    page.goto(f"{BASE}/projects/1/schedule", wait_until="networkidle")

    # The how-to-use helper is a panel too; the three being counted here are the
    # squeeze and the tables folded under each chart.
    panels = page.locator("details.panel:not(.guide-strip)")
    if panels.count() != 3:
        raise AssertionError(f"expected three folded panels, found {panels.count()}")
    if panels.first.get_attribute("open") is not None:
        raise AssertionError("the page should open on the chart, not the table")

    # Hovering a bar — over its WBS label, left of the plotting area — says
    # what the line is about.
    label = page.locator(".chart svg text").filter(has_text="1.1").first
    label.scroll_into_view_if_needed()
    at = label.bounding_box()
    page.mouse.move(at["x"] + at["width"] / 2, at["y"] + at["height"] / 2)
    page.wait_for_selector(".chart-tip:not([hidden])", timeout=4000)
    said = page.locator(".chart-tip:not([hidden])").first.inner_text()
    for expected in ("1.1", "Start", "Duration", "Float"):
        if expected not in said:
            raise AssertionError(f"the bar's tooltip does not say {expected!r}: {said!r}")

    # The toggle opens the table, and the choice is remembered.
    panels.first.locator("summary").click()
    page.wait_for_timeout(400)
    if panels.first.get_attribute("open") is None:
        raise AssertionError("the details toggle did not open the table")
    page.reload(wait_until="networkidle")
    if page.locator("details.panel:not(.guide-strip)").first.get_attribute("open") is None:
        raise AssertionError("the browser should remember the panel was left open")

    # Where each path ends, and how many there are.
    page.locator("#network").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    if page.locator("#network rect[stroke*='series-1']").count() == 0:
        raise AssertionError("a line nothing waits on should be drawn blue")
    body = page.text_content("body")
    for expected in ("unique path", "End of a path", "nothing waits on"):
        if expected not in body:
            raise AssertionError(f"the diagram does not say {expected!r}")
    page.screenshot(path=str(SHOTS / "25-schedule-reading.png"), full_page=True)


def _schedule_simplify(page) -> None:
    """Each kind of link reads differently, and Simplify untangles the picture
    without the page reloading."""
    _schedule_page(page, "links")

    # Wire the diagram up crossed, with one of each kind of link.
    wires = [("11", "1", "FS", "0"), ("10", "2", "SS", "-5"),
             ("9", "3", "FF", "10"), ("8", "4", "SF", "3")]
    for successor, predecessor, kind, lag in wires:
        page.select_option("form[data-live-link] select[name=successor_id]", value=successor)
        page.select_option("form[data-live-link] select[name=predecessor_id]", value=predecessor)
        page.select_option("form[data-live-link] select[name=kind]", kind)
        page.fill("form[data-live-link] input[name=lag_days]", lag)
        page.click("button:has-text('Link them')")
        page.wait_for_timeout(1400)

    page.locator("#network").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / "26-links-tangled.png"), full_page=True)

    url = page.url
    page.click("button:has-text('Simplify')")
    page.wait_for_selector(".flash:has-text('Simplif')", timeout=8000)
    said = page.locator(".flash").last.inner_text()
    if page.url != url:
        raise AssertionError("simplifying should not reload the page")
    if "down from" not in said:
        raise AssertionError(f"expected a count of the crossings it removed: {said!r}")

    # And it was written down, so the boxes can be nudged from there.
    page.reload(wait_until="networkidle")
    placed = page.eval_on_selector_all(
        "#network .net-node", "nodes => nodes.map(n => n.dataset.y)")
    if len(set(placed)) < 2:
        raise AssertionError("the new places did not stick")
    page.screenshot(path=str(SHOTS / "27-links-simplified.png"), full_page=True)

    # Tidy up forgets them again.
    page.click("button:has-text('Tidy up')")
    page.wait_for_timeout(1500)
    if page.locator("#network .net-node").count() == 0:
        raise AssertionError("the diagram disappeared")


def _diagram_links(page) -> None:
    """A link is drawn by dragging from a box's plug, and removed by clicking
    the line — both without the page reloading."""
    _schedule_page(page, "links")
    page.locator("#network").scroll_into_view_if_needed()
    page.wait_for_timeout(400)

    before = page.locator("#network path.net-edge").count()
    url = page.url

    # Drag from the plug on one box onto another. Some pairs are already
    # linked, and one the wrong way round would close a loop, so the first
    # pair the programme accepts is the one that proves the drag works.
    boxes = page.locator("#network .net-node.movable")
    at = boxes.first.locator(".net-plug").bounding_box()
    after = before
    for index in range(boxes.count() - 1, 0, -1):
        onto = boxes.nth(index).bounding_box()
        page.mouse.move(at["x"] + at["width"] / 2, at["y"] + at["height"] / 2)
        page.mouse.down()
        page.mouse.move(onto["x"] + onto["width"] / 2, onto["y"] + onto["height"] / 2, steps=12)
        page.mouse.up()
        page.wait_for_timeout(2200)
        after = page.locator("#network path.net-edge").count()
        if after > before:
            break
        at = boxes.first.locator(".net-plug").bounding_box()

    if page.url != url:
        raise AssertionError("drawing a link should not reload the page")
    if after <= before:
        raise AssertionError(f"the link was not drawn: {before} -> {after}")
    page.screenshot(path=str(SHOTS / "28-drawn-link.png"), full_page=True)

    # Clicking a line takes it away again.
    page.locator("#network path.net-edge").last.click(force=True)
    page.wait_for_timeout(2200)
    if page.url != url:
        raise AssertionError("removing a link should not reload the page")
    if page.locator("#network path.net-edge").count() >= after:
        raise AssertionError("the line was not removed")


def _task_panel(page) -> None:
    """Clicking a deliverable opens it, dates and dependencies together."""
    _schedule_page(page, "dates")
    page.locator("a.open-task").first.click()
    page.wait_for_selector("#task-panel:not([hidden])", timeout=8000)

    said = page.locator("#task-panel").inner_text()
    for expected in ("START", "DURATION", "SUBMISSION", "TEAM", "FLOAT",
                     "Waits for", "Waited on by"):
        if expected not in said:
            raise AssertionError(f"the panel does not show {expected!r}")
    page.screenshot(path=str(SHOTS / "29-task-panel.png"))

    # A dependency made in the panel lands without the page reloading.
    url = page.url
    page.select_option("#task-panel select[name=predecessor_id]", index=6)
    page.click("#task-panel button:has-text('Link')")
    page.wait_for_timeout(2400)
    if page.url != url:
        raise AssertionError("linking from the panel should not reload the page")
    if "Nothing — it can start" in page.locator("#task-panel").inner_text():
        raise AssertionError("the panel did not pick the new dependency up")

    # A date changed in the panel is a date changed on the schedule.
    page.locator("#task-panel .cell-open[data-cell='plan-duration']").click()
    page.wait_for_selector("form.cell-form input[name=duration_days]", timeout=6000)
    page.fill("form.cell-form input[name=duration_days]", "17")
    page.locator("form.cell-form input[name=duration_days]").blur()
    page.wait_for_timeout(2000)
    if "17d" not in page.locator("#duration-1").inner_text():
        raise AssertionError("the schedule row did not follow the panel")

    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    if not page.locator("#task-panel").is_hidden():
        raise AssertionError("Escape should close the panel")


def _teams(page) -> None:
    """A team is a working week and its holidays; a line planned on one counts
    its duration in the days that team is actually in."""
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    page.fill("input[name=password]", "2026")
    page.click("button:has-text('Unlock')")
    page.wait_for_timeout(700)

    for name, week, office in (("Cairo", "1111001", "cairo"), ("Beirut", "1111100", "beirut")):
        page.fill("form[action$='/setup/teams'] input[name=name]", name)
        page.select_option("form[action$='/setup/teams'] select[name=workdays]", week)
        page.select_option("form[action$='/setup/teams'] select[name=office]", office)
        page.click("form[action$='/setup/teams'] button")
        page.wait_for_timeout(900)

    body = page.text_content("body")
    for expected in ("Cairo", "Beirut", "Sunday to Thursday", "Monday to Friday"):
        if expected not in body:
            raise AssertionError(f"the setup sheet does not show {expected!r}")

    page.fill("form[action$='/setup/holidays'] input[name=holiday_date]", "28/09/2026")
    page.fill("form[action$='/setup/holidays'] input[name=name]", "National day")
    page.click("form[action$='/setup/holidays'] button")
    page.wait_for_selector("text=Holiday added >> visible=true", timeout=8000)
    page.screenshot(path=str(SHOTS / "30-teams.png"), full_page=True)

    # A line's team is not set on the line: it comes from the trades carrying
    # it, through the office each trade sits in. Put every trade in Cairo and
    # every line follows.
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    offices = page.locator("select[name^='trade_'][name$='_office']")
    for n in range(offices.count()):
        offices.nth(n).select_option("cairo")
    page.click("button:has-text('Save all changes')")
    page.wait_for_selector("text=Saved — project settings >> visible=true", timeout=8000)

    _schedule_page(page, "dates")
    if "Cairo" not in page.locator("#team-1").inner_text():
        raise AssertionError("the line did not take its team from its trades")
    if page.locator("#team-1 .cell-open").count():
        raise AssertionError("the team is read from the trades, not chosen on the line")

    # And a holiday in the week before a submission is said out loud.
    if page.locator(".holiday-flag").count() == 0:
        raise AssertionError("a holiday before a submission should be flagged")
    if "Holidays before a submission" not in page.text_content("body"):
        raise AssertionError("the tile counting them is missing")
    page.screenshot(path=str(SHOTS / "31-holiday-flag.png"), full_page=True)

    # The sheet was unlocked to get here; a later step checks it starts locked.
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    page.click("button:has-text('Lock again')")
    page.wait_for_timeout(600)


def _print_one_chart(page) -> None:
    """A chart prints alone: the sheet holds the project header and that card,
    and nothing else."""
    _schedule_page(page)

    for label, heading in (("Print the bar chart", "Programme"),
                           ("Print the diagram", "Dependencies")):
        page.click(f"button:has-text('{label}')")
        page.wait_for_timeout(400)
        marked = page.evaluate(
            "() => [...document.querySelectorAll('.print-keep h2')].map(h => h.textContent.trim())")
        if marked != [heading]:
            raise AssertionError(f"{label} marked {marked}, not [{heading!r}]")

        page.emulate_media(media="print")
        page.wait_for_timeout(250)
        on_paper = page.evaluate("""() => [...document.querySelectorAll('main .wrap > *')]
            .filter(node => getComputedStyle(node).display !== 'none')
            .map(node => (node.querySelector('h2') || node).textContent.trim().slice(0, 20))""")
        if len(on_paper) != 2 or heading not in on_paper[-1]:
            raise AssertionError(f"the sheet holds {on_paper}, not just the header and {heading}")
        if page.locator(".net-plug").count() and not page.locator(".net-plug").first.is_hidden():
            raise AssertionError("the editing plugs should not go on paper")
        page.screenshot(path=str(SHOTS / f"32-print-{heading.lower()}.png"), full_page=True)

        page.emulate_media(media="screen")
        page.evaluate("""() => {
            document.body.classList.remove('print-one');
            document.querySelectorAll('.print-keep').forEach(c => c.classList.remove('print-keep'));
        }""")
        page.wait_for_timeout(200)

    # And the whole-page print is untouched.
    page.click("button:has-text('Print / PDF')")
    page.wait_for_timeout(300)
    if page.evaluate("() => document.body.classList.contains('print-one')"):
        raise AssertionError("a whole-page print should not leave one card marked")


def _critical_path(page) -> None:
    """The run of work that sets the end date, unbroken, in the order it runs —
    and still there when something unsequenced finishes after it."""
    _schedule_page(page, "links")

    steps = page.locator(".path-step")
    if steps.count() == 0:
        raise AssertionError("the earlier steps linked deliverables, so there should be a path")

    said = page.locator(".card:has(h2:text-is('Critical path')) .card-head p").inner_text()
    if "sets the end date" not in said:
        raise AssertionError(f"the path card does not say what it is: {said!r}")

    # Every step in date order, and each one red on the table below.
    dates = page.locator(".path-step .path-dates")
    starts = [dates.nth(i).inner_text().split("→")[0].strip() for i in range(dates.count())]
    ordered = sorted(starts, key=lambda d: tuple(reversed(d.split("/"))))
    if starts != ordered:
        raise AssertionError(f"the path is not in the order the work runs: {starts}")
    if page.locator("tr.is-critical").count() < steps.count():
        raise AssertionError("every line on the path should be marked on the table")

    # Push an unsequenced deliverable out past the end of the run: the path
    # must not vanish with it.
    was = steps.count()
    _schedule_page(page, "dates")
    last = page.locator("tbody tr[id^='task-']").last
    row = last.get_attribute("id").split("-")[1]
    page.locator(f"#start-{row} .cell-open").click()
    page.wait_for_selector("form.cell-form input[name=start_date]", timeout=6000)
    page.fill("form.cell-form input[name=start_date]", "01/06/2030")
    page.locator("form.cell-form input[name=start_date]").blur()
    page.wait_for_timeout(2200)

    _schedule_page(page)
    now = page.locator(".path-step").count()
    if now != was:
        raise AssertionError(
            f"an unsequenced line finishing last should not change the path: {was} -> {now}")
    page.screenshot(path=str(SHOTS / "33-critical-path.png"), full_page=True)


def _dates_read_dd_mm(page) -> None:
    body = page.text_content("body")
    if "31/08/2026" not in body:
        raise AssertionError("dates should read dd/mm/yyyy")
    if page.locator("input[type=date]").count():
        raise AssertionError("a native date picker would follow the machine's locale")


def _internal_register(page) -> None:
    """The internal weekly list: its own tab and path, separate from the
    client's minutes, and readable as it stood on a past date."""
    page.goto(f"{BASE}/projects/1/internal/register", wait_until="networkidle")
    page.wait_for_selector("h1:has-text('Internal weekly')", timeout=8000)
    if "/internal" not in page.url:
        raise AssertionError(f"the internal register should have its own path: {page.url}")
    if "kept for us, not for the client" not in page.text_content("body"):
        raise AssertionError("the page should say whose register this is")

    # A weekly meeting and two requirements on it.
    page.fill("form[action*='/meetings'] input[name=title]", "Weekly internal – week 1")
    page.fill("form[action*='/meetings'] input[name=meeting_date]", "05/01/2026")
    page.click("form[action*='/meetings'] button:has-text('Add')")
    page.wait_for_selector("h1:has-text('Weekly internal')", timeout=8000)

    for subject, due in (("Issue the mooring calc note", "12/01/2026"),
                         ("Chase the bathymetry survey", "20/01/2026")):
        page.fill("form[action*='/items'] input[name=subject]", subject)
        page.fill("form[action*='/items'] input[name=due_date]", due)
        # Raised on the meeting's own date, which the page carries for us.
        page.click("form[action*='/items'] button:has-text('Add item')")
        page.wait_for_timeout(900)

    page.goto(f"{BASE}/projects/1/internal/register?filter=all", wait_until="networkidle")
    rows = page.locator("tbody tr[id^='item-']")
    if rows.count() != 2:
        raise AssertionError(f"expected the two internal items, found {rows.count()}")

    # Close one on the day it was actually closed.
    first = rows.first.get_attribute("id").split("-")[1]
    page.goto(f"{BASE}/projects/1/internal/register?filter=all&edit={first}", wait_until="networkidle")
    editor = page.locator(f"#edit-{first} form.item-form")
    editor.locator("select[name=status]").select_option("closed")
    editor.locator("input[name=closed_date]").fill("10/01/2026")
    editor.locator("button:has-text('Save item')").click()
    page.wait_for_timeout(1200)

    # The client asks where things stood on the fifteenth.
    page.goto(f"{BASE}/projects/1/internal/register?filter=all&as_at=15/01/2026", wait_until="networkidle")
    said = page.locator(".as-at-banner").inner_text()
    if "as it stood on 15/01/2026" not in said:
        raise AssertionError(f"the page does not say it is showing a past date: {said!r}")
    if "1 closed" not in said:
        raise AssertionError(f"the note should count what was closed by then: {said!r}")
    page.screenshot(path=str(SHOTS / "34-internal-as-at.png"), full_page=True)

    # A week earlier, that item had not been closed yet.
    page.goto(f"{BASE}/projects/1/internal/register?filter=all&as_at=08/01/2026", wait_until="networkidle")
    if "0 closed" not in page.locator(".as-at-banner").inner_text():
        raise AssertionError("an item closed on the tenth was still open on the eighth")

    # Before anything was raised, the register was empty.
    page.goto(f"{BASE}/projects/1/internal/register?filter=all&as_at=01/01/2020", wait_until="networkidle")
    if page.locator("tbody tr[id^='item-']").count() != 0:
        raise AssertionError("nothing had been raised in 2020")

    # And none of it reached the client's minutes.
    page.goto(f"{BASE}/projects/1/minutes?filter=all", wait_until="networkidle")
    if "Issue the mooring calc note" in page.text_content("body"):
        raise AssertionError("the internal list must not show in the client's minutes")

    # It goes to Word under its own name, saying the date it was read at.
    page.goto(f"{BASE}/projects/1/internal/register?filter=all&as_at=15/01/2026", wait_until="networkidle")
    with page.expect_download(timeout=10000) as download:
        page.click("a:has-text('Export Word')")
    name = download.value.suggested_filename
    if "internal" not in name:
        raise AssertionError(f"the internal register downloaded as {name}")


def _reading(cell: str) -> str:
    """What a progress cell says it stands at, without the plan beside it."""
    return " ".join(cell.split("plan")[0].split())


def _this_week(page) -> None:
    """The Task List tab opens on the week: what the programme and both
    registers want between Monday and Sunday, in one list, editable in place."""
    page.click("nav.tabs a:has-text('Task List')")
    page.wait_for_selector("h1:has-text('This week')", timeout=8000)
    if not page.url.rstrip("/").endswith("/internal"):
        raise AssertionError(f"the Task List tab should open on the week: {page.url}")

    body = page.text_content("body")
    for expected in ("Wanted this week", "Already late", "The week is worth"):
        if expected not in body:
            raise AssertionError(f"the week does not show {expected!r}")

    # It says where each row came from — that is the point of the page.
    if page.locator("a.badge:has-text('Schedule')").count() == 0:
        raise AssertionError("the week should say which rows came off the programme")

    # Change progress here; it is the deliverable itself, not a copy of it.
    # A select saves the moment it is changed, as it does everywhere else.
    cell = page.locator("a.cell-open[data-rows='t'][data-cell='status']").first
    task_id = cell.get_attribute("data-item")
    before = _reading(page.text_content(f"#tprogress-{task_id}"))
    cell.click()
    page.wait_for_selector(f"#tprogress-{task_id} select", timeout=4000)
    picked = page.locator(f"#tprogress-{task_id} select option").nth(3).get_attribute("value")
    page.select_option(f"#tprogress-{task_id} select", picked)
    page.wait_for_selector(f"#tprogress-{task_id} .cell-open", timeout=8000)
    after = _reading(page.text_content(f"#tprogress-{task_id}"))
    if after == before:
        raise AssertionError(f"the week's progress cell did not take the change: {after!r}")

    # And it is the same record the Progress tab shows, not a copy of it.
    page.goto(f"{BASE}/projects/1/tasks", wait_until="networkidle")
    row = page.locator(f"tr#task-{task_id}")
    if row.count() == 0:
        raise AssertionError("the deliverable is not on the Progress tab")
    if _reading(row.locator("[id^=progress-]").inner_text()) != after:
        raise AssertionError("progress recorded on the week should show on the Progress tab")

    # One button opens the weekly meeting, and pressing it again opens the same one.
    page.goto(f"{BASE}/projects/1/internal", wait_until="networkidle")
    page.click("button:has-text('the weekly meeting')")
    page.wait_for_selector("h1", timeout=8000)
    if "/meetings/" not in page.url:
        raise AssertionError(f"the weekly button should open a meeting: {page.url}")
    opened = page.url

    page.goto(f"{BASE}/projects/1/internal", wait_until="networkidle")
    page.click("button:has-text('the weekly meeting')")
    page.wait_for_selector("h1", timeout=8000)
    if page.url != opened:
        raise AssertionError("pressing it again should open the same meeting, not a second one")

    page.goto(f"{BASE}/projects/1/internal", wait_until="networkidle")
    page.screenshot(path=str(SHOTS / "36-this-week.png"), full_page=True)


def _how_to_use(page) -> None:
    """A helper at the top of every tab, and one page holding every definition."""
    page.goto(f"{BASE}/projects/1/schedule", wait_until="networkidle")
    strip = page.locator("details.guide-strip")
    if strip.count() == 0:
        raise AssertionError("the Schedule tab has no helper")
    if strip.first.get_attribute("open") is not None:
        raise AssertionError("the helper should start folded away")
    if "How to use the Schedule tab" not in strip.inner_text():
        raise AssertionError("the helper does not say which tab it is for")

    # Opened, it stays open — the browser remembers, so somebody working
    # through it does not reopen it on every page.
    page.click("details.guide-strip > summary")
    page.wait_for_timeout(400)
    page.reload(wait_until="networkidle")
    if not page.locator("details.guide-strip[open]").count():
        raise AssertionError("a helper opened should stay open")
    page.click("details.guide-strip > summary")
    page.wait_for_timeout(400)

    # Every tab has one of its own.
    for path, expected in (("/", "How to use the Dashboard tab"),
                           ("/tasks", "How to use the Progress tab"),
                           ("/internal", "How to use the Task List tab"),
                           ("/setup", "How to use the Setup tab")):
        page.goto(f"{BASE}/projects/1{path}", wait_until="networkidle")
        if expected not in page.text_content("body"):
            raise AssertionError(f"{path} has no helper")

    # And the tab that holds the lot.
    page.click("nav.tabs a:has-text('How to use')")
    page.wait_for_selector("h1:has-text('How to use this')", timeout=8000)
    body = page.text_content("body")
    for expected in ("Earned progress", "Critical path", "Run-up holidays", "CPI",
                     "The week is worth", "As at", "Code B"):
        if expected not in body:
            raise AssertionError(f"the guide does not define {expected!r}")

    page.fill("input[name=q]", "float")
    page.click("button:has-text('Search')")
    page.wait_for_timeout(600)
    narrowed = page.text_content("body")
    if "Float" not in narrowed or "Man-month" in narrowed:
        raise AssertionError("searching the definitions did not narrow them")
    page.screenshot(path=str(SHOTS / "37-how-to-use.png"), full_page=True)


def _overview(page) -> None:
    """The dashboard says when the project runs and how much room is left."""
    page.goto(f"{BASE}/projects/1/", wait_until="networkidle")
    card = _card(page, "Overview")
    said = card.inner_text()
    for expected in ("Starts", "Finishes", "Contract date", "Float", "Earned hours"):
        if expected not in said:
            raise AssertionError(f"the overview does not show {expected!r}")
    if not re.search(r"-?\d+d", said):
        raise AssertionError(f"the overview shows no float in days: {said!r}")
    if not re.search(r"\d{2}/\d{2}/\d{4}", said):
        raise AssertionError("the overview shows no dates")


def _row_reads(page, task_id: int) -> str:
    """What the Progress tab says one deliverable has reached, fetched through
    the browser's own session rather than by navigating to it."""
    body = page.request.get(f"{BASE}/projects/1/tasks").text()
    found = re.search(r'id="progress-%d"(.*?)</span>' % task_id, body, re.S)
    if not found:
        raise AssertionError(f"deliverable {task_id} is not on the Progress tab")
    percent = re.search(r"(\d+)%", found.group(1))
    return (percent.group(0) if percent else "")


def _assistant(page) -> None:
    """The chat: it answers, it shows what it would change, and nothing changes
    until Apply is pressed.

    Anthropic is stood in for by a small server the test runs itself — pointing
    a smoke test at somebody's paid API would make it slow, flaky and expensive,
    and what is worth checking here is the page, not the model."""
    page.click("nav.tabs a:has-text('Carmen')")
    page.wait_for_selector("h1:has-text('Carmen')", timeout=8000)
    if "What she can do" not in page.text_content("body"):
        raise AssertionError("Carmen's tab does not say what she can do")

    if not os.environ.get("CLAUDE_STAND_IN"):
        # Nothing to talk to; what is checked is that the page says where the
        # key goes.
        if "Open Setup" not in page.text_content("body"):
            raise AssertionError("the page does not point at Setup for the key")
        page.screenshot(path=str(SHOTS / "38-assistant.png"), full_page=True)
        return

    # The key lives on Setup — one place, administrators only.
    if not page.locator("#chat-form textarea:not([disabled])").count():
        page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
        page.fill("input[name=anthropic_key]", "sk-ant-stand-in")
        page.click("form:has(input[name=anthropic_key]) button:has-text('Save')")
        page.wait_for_selector(".flash", timeout=8000)
        page.goto(f"{BASE}/projects/1/assistant", wait_until="networkidle")
    page.wait_for_selector("#chat-form textarea:not([disabled])", timeout=8000)

    # A question that reads the project.
    page.fill("#chat-form textarea[name=question]", "How is the project doing?")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-line.assistant:not(.thinking) .chat-used", timeout=25000)
    said = page.locator("#chat .chat-line.assistant").last.inner_text()
    if "overview" not in said:
        raise AssertionError(f"the answer does not say what it read: {said!r}")

    # A change: staged, listed, and not done.
    before = _row_reads(page, 1)
    page.fill("#chat-form textarea[name=question]", "Set 1.1 to 40%")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-staged", timeout=25000)
    staged = page.locator("#chat .chat-staged").last.inner_text()
    if "40%" not in staged or "nothing has changed yet" not in staged.lower():
        raise AssertionError(f"the staged change does not read right: {staged!r}")

    # Read without leaving the page: navigating away would throw the chat away,
    # and the point is that nothing has changed while the proposal is still on
    # screen waiting to be approved.
    if _row_reads(page, 1) != before:
        raise AssertionError("a staged change must not have been applied already")

    page.click("#chat .chat-staged button:has-text('Apply')")
    page.wait_for_selector("#chat .chat-staged:has-text('Applied')", timeout=15000)
    page.screenshot(path=str(SHOTS / "38-assistant.png"), full_page=True)

    if _row_reads(page, 1) != "40%":
        raise AssertionError("applying should have recorded the progress")

    # The conversation is kept: it appears on the left, and reopening it brings
    # back what was said rather than an empty box. The list refreshes itself a
    # moment after the answer lands, so it is waited for rather than assumed.
    page.wait_for_selector(".chat-thread", timeout=8000)
    title = page.locator(".chat-thread").first.inner_text()
    if "project doing" not in title.lower():
        raise AssertionError(f"the conversation is not named after the question: {title!r}")

    page.goto(f"{BASE}/projects/1/assistant", wait_until="networkidle")
    page.click(".chat-thread")
    page.wait_for_selector(".chat-line.you", timeout=8000)
    said = page.text_content("#chat")
    if "How is the project doing?" not in said:
        raise AssertionError("reopening the conversation lost the question")
    if "overview" not in said:
        raise AssertionError("reopening the conversation lost the answer")
    page.screenshot(path=str(SHOTS / "41-conversations.png"), full_page=True)


def _carmen_files(page) -> None:
    """A file goes up with the question, is kept with the conversation, and a
    document comes back the other way when one is asked for."""
    if not os.environ.get("CLAUDE_STAND_IN"):
        return

    page.goto(f"{BASE}/projects/1/assistant", wait_until="networkidle")
    page.wait_for_selector("#chat-form textarea:not([disabled])", timeout=8000)

    note = SHOTS / "client-letter.txt"
    note.write_text("Sibline Port — the client asks for the bathymetry brief "
                    "by 20/09/2026.\n", encoding="utf-8")

    # Picked, and shown in the composer before it is sent.
    page.set_input_files("#chat-form input[data-attach]", str(note))
    page.wait_for_selector(".chat-attached:not([hidden])", timeout=8000)
    if "client-letter.txt" not in page.text_content(".chat-attached"):
        raise AssertionError("the attached file is not shown before it goes")

    page.fill("#chat-form textarea[name=question]", "What does this letter ask for?")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-line.assistant:not(.thinking) .chat-used",
                           timeout=25000)
    if "client-letter.txt" not in page.locator("#chat .chat-line.you").last.inner_text():
        raise AssertionError("the question does not carry what was attached")

    # Kept: a reload lands back in the conversation with the file still on it,
    # and pressing it gives the file back.
    page.reload(wait_until="networkidle")
    page.wait_for_selector("a.chat-file", timeout=8000)
    where = page.locator("a.chat-file").last.get_attribute("href")
    came = page.request.get(where if where.startswith("http") else BASE + where)
    if not came.ok or b"bathymetry" not in came.body():
        raise AssertionError("the attachment did not come back down")

    # And a document the other way.
    page.fill("#chat-form textarea[name=question]",
              "Send me the action register as a Word document")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-line.assistant:not(.thinking) a[href*=register]",
                           timeout=25000)
    link = page.locator("#chat .chat-line.assistant a[href*=register]").last
    if "Download" not in link.inner_text():
        raise AssertionError(f"the document is not offered as a download: "
                             f"{link.inner_text()!r}")
    file = page.request.get(BASE + link.get_attribute("href"))
    if not file.ok or file.body()[:2] != b"PK":
        raise AssertionError("the register did not come back as a Word file")
    page.screenshot(path=str(SHOTS / "44-carmen-files.png"), full_page=True)


def _minutes_export(page) -> None:
    """The issued minutes: a PDF built on the template, with a PDF attached to
    it compiled onto the end."""
    page.goto(f"{BASE}/projects/1/minutes", wait_until="networkidle")
    _put_carmen_away(page)

    # The ordering option lives with the roster and covers the whole project.
    if page.locator("select[name=attendee_order]").count() == 0:
        raise AssertionError("the attendance order cannot be set")
    page.select_option("select[name=attendee_order]", "seniority")
    page.click("form[action$='/attendee-order'] button")
    page.wait_for_selector("text=every set of minutes >> visible=true", timeout=8000)

    page.goto(f"{BASE}/projects/1/minutes", wait_until="networkidle")
    _put_carmen_away(page)
    page.click("a[href*='/minutes/meetings/']")
    page.wait_for_selector("text=Attachments >> visible=true", timeout=8000)

    # A PDF to attach: the app's own export of these minutes will do.
    where = page.url.split("?")[0]
    saved = str(SHOTS / "attachment.pdf")
    answer = page.request.get(where + ".pdf")
    if not answer.ok:
        raise AssertionError(f"the minutes PDF came back {answer.status}")
    before = answer.body()
    with open(saved, "wb") as file:
        file.write(before)
    if before[:5] != b"%PDF-":
        raise AssertionError("that is not a PDF")

    page.fill("form[action$='/attachments'] input[name=name]", "Kick-off presentation")
    page.set_input_files("form[action$='/attachments'] input[name=file]", saved)
    page.click("form[action$='/attachments'] button[type=submit]")
    page.wait_for_selector("text=compiled into the exported PDF >> visible=true", timeout=8000)
    if "Kick-off presentation" not in page.text_content("body"):
        raise AssertionError("the attachment is not listed")

    after = page.request.get(where + ".pdf").body()
    if len(after) <= len(before):
        raise AssertionError("the attachment was not compiled into the export")
    page.screenshot(path=str(SHOTS / "42-minutes-export.png"), full_page=True)


def _minutes_template(page) -> None:
    """The issued layout comes off a Word document anybody can edit: download
    it, change a word, upload it back, and the export follows."""
    import io
    import zipfile

    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    _put_carmen_away(page)
    if "Minutes template" not in page.text_content("body"):
        raise AssertionError("Setup has no minutes template card")

    got = page.request.get(f"{BASE}/projects/1/setup/minutes-template.docx")
    if not got.ok:
        raise AssertionError(f"the template came back {got.status}")
    template = got.body()
    if b"{{item.subject}}" not in template.replace(b"\x00", b""):
        # The placeholders live inside the zip, so it is opened to look.
        with zipfile.ZipFile(io.BytesIO(template)) as book:
            body = book.read("word/document.xml").decode("utf-8")
        if "{{item.subject}}" not in body:
            raise AssertionError("the template carries no placeholders")

    # Edited the way somebody would in Word, then uploaded back.
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template)) as src, \
            zipfile.ZipFile(changed, "w") as made:
        for name in src.namelist():
            data = src.read(name)
            if name == "word/document.xml":
                data = data.decode("utf-8").replace(
                    "Items and Agreement", "Points discussed").encode("utf-8")
            made.writestr(name, data)

    edited = SHOTS / "minutes-template.docx"
    edited.write_bytes(changed.getvalue())
    if page.locator("input[name=password]").count():
        page.fill("input[name=password]", "2026")
        page.click("button:has-text('Unlock')")
        page.wait_for_selector("text=Setup sheet unlocked >> visible=true", timeout=8000)
    page.set_input_files("form[action$='/setup/minutes-template'] input[type=file]", str(edited))
    page.click("form[action$='/setup/minutes-template'] button[type=submit]")
    page.wait_for_selector("text=placeholders found >> visible=true", timeout=8000)
    page.screenshot(path=str(SHOTS / "45-minutes-template.png"), full_page=True)

    page.goto(f"{BASE}/projects/1/minutes", wait_until="networkidle")
    _put_carmen_away(page)
    page.click("a[href*='/minutes/meetings/']")
    where = page.url.split("?")[0]
    made = page.request.get(where + ".docx").body()
    with zipfile.ZipFile(io.BytesIO(made)) as book:
        body = book.read("word/document.xml").decode("utf-8")
    if "Points discussed" not in body:
        raise AssertionError("the export is not built from the uploaded template")
    if "{{" in body:
        raise AssertionError("a placeholder was left unfilled")

    # And back to the built-in layout, so the rest of the run is unaffected.
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    _put_carmen_away(page)
    # The page already accepts every dialog; a second handler here would race
    # the first for the same one.
    page.click("form[action$='/setup/minutes-template/remove'] button")
    page.wait_for_selector("text=built-in layout >> visible=true", timeout=8000)

    # Left as it was found: a later step checks the sheet starts locked.
    if page.locator("button:has-text('Lock again')").count():
        page.click("button:has-text('Lock again')")
        page.wait_for_selector("text=Unlock >> visible=true", timeout=8000)


def _attendee_order(page) -> None:
    """The roster's order is the order the export lists people in, and a person
    moves up it where they stand."""
    page.goto(f"{BASE}/projects/1/minutes", wait_until="networkidle")
    _put_carmen_away(page)
    rows = page.locator("tbody[data-live-list='person'] tr[id^=person-]")
    if rows.count() < 2:
        raise AssertionError("two people are needed to reorder them")

    was = rows.first.inner_text().strip()
    second = rows.nth(1).inner_text().strip()
    page.evaluate("() => { window.__stayed = true; }")
    rows.nth(1).locator("[data-move=up]").click()
    page.wait_for_function(
        "was => { const row = document.querySelector("
        "'tbody[data-live-list=\"person\"] tr[id^=person-]');"
        " return row && row.innerText.trim() !== was; }",
        arg=was, timeout=8000)

    if not page.evaluate("() => window.__stayed === true"):
        raise AssertionError("the page reloaded — the move should happen where it stands")
    if second.split("\n")[0] not in rows.first.inner_text():
        raise AssertionError("the wrong row moved")
    page.screenshot(path=str(SHOTS / "46-attendee-order.png"), full_page=True)


def _minutes_live_move(page) -> None:
    """The arrows move a row where it stands and renumber it, without a reload."""
    page.goto(f"{BASE}/projects/1/minutes", wait_until="networkidle")
    _put_carmen_away(page)
    page.click("a[href*='/minutes/meetings/']")
    page.wait_for_selector("tbody[data-items-table] tr[id^=item-]", timeout=8000)

    # Item rows only: each one carries a hidden edit row behind it.
    rows = page.locator("tbody[data-items-table] tr[id^=item-]")
    if rows.count() < 2:
        raise AssertionError("two items are needed to reorder them")
    was = rows.first.inner_text()
    page.evaluate("() => { window.__stayed = true; }")

    rows.nth(1).locator("[data-move=up]").click()
    page.wait_for_function(
        "was => document.querySelector('tbody[data-items-table] tr[id^=item-]').innerText !== was",
        arg=was, timeout=8000)

    if not page.evaluate("() => window.__stayed === true"):
        raise AssertionError("the page reloaded — the move should happen where it stands")
    numbers = [t.strip() for t in
               page.locator("tbody[data-items-table] tr[id^=item-] td[data-ref]").all_inner_texts()]
    if numbers != sorted(numbers):
        raise AssertionError(f"the items did not renumber in order: {numbers}")
    page.screenshot(path=str(SHOTS / "43-minutes-move.png"), full_page=True)


def _assistant_changes_the_setup(page) -> None:
    """The setup sheet, from the chat: a trade added, an office set, and then
    the one change nobody would make by hand fifty-five times — a trade taking
    a share of every deliverable, with the rest rescaled to fit."""
    if not os.environ.get("CLAUDE_STAND_IN"):
        return

    # The setup sheet's own guard applies to a change she staged, so it has to
    # be unlocked first — the same as making the change by hand.
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    if page.locator("input[name=password]").count():
        page.fill("input[name=password]", "2026")
        page.click("button:has-text('Unlock')")
        page.wait_for_selector("text=Setup sheet unlocked >> visible=true", timeout=8000)

    page.goto(f"{BASE}/projects/1/assistant", wait_until="networkidle")
    page.wait_for_selector("#chat-form textarea:not([disabled])", timeout=8000)

    # First the trade itself.
    page.fill("#chat-form textarea[name=question]",
              "Add a trade called Project Manager, Beirut, 400 hours")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-staged", timeout=25000)
    staged = page.locator("#chat .chat-staged").last.inner_text()
    if "Project Manager" not in staged or "Beirut" not in staged:
        raise AssertionError(f"adding a trade does not read right: {staged!r}")
    page.click("#chat .chat-staged button:has-text('Apply')")
    page.wait_for_selector("#chat .chat-staged:has-text('Applied')", timeout=15000)

    # Then its share of everything, as one thing to approve.
    page.fill("#chat-form textarea[name=question]",
              "Give the Project Manager 10% of every deliverable")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat .chat-staged:not(:has-text('Applied'))", timeout=25000)
    staged = page.locator("#chat .chat-staged").last.inner_text()
    if "every deliverable" not in staged or "rescaled" not in staged:
        raise AssertionError(f"the bulk change does not say what it does: {staged!r}")
    page.click("#chat .chat-staged:not(:has-text('Applied')) button:has-text('Apply')")
    page.wait_for_selector("#chat .chat-staged:has-text('Applied')", timeout=20000)
    page.screenshot(path=str(SHOTS / "40-carmen-setup.png"), full_page=True)

    # And it reached the project: the trade is on the budget, carrying scope.
    page.goto(f"{BASE}/projects/1/budget", wait_until="networkidle")
    body = page.text_content("body")
    if "Project Manager" not in body:
        raise AssertionError("the new trade is not on the budget")

    # And every split still totals 100%, which is the whole point of rescaling
    # the others rather than bolting a tenth on the side.
    page.goto(f"{BASE}/projects/1/setup", wait_until="networkidle")
    page.click("summary:has-text('deliverable')" if page.locator(
        "summary:has-text('deliverable')").count() else "body")
    shares = page.locator("input[name*='_alloc_']")
    if shares.count() == 0:
        raise AssertionError("the trade split is not on the setup sheet")
    off = page.locator(".split-total.bad-text").count()
    if off:
        raise AssertionError(f"{off} deliverables no longer total 100%")

    # Lock it again on the way out: the sheet re-locks itself in real use, and
    # a later step here reads it as it would be found.
    page.click("button:has-text('Lock again')")
    page.wait_for_selector("text=Setup sheet locked >> visible=true", timeout=8000)


def _deck(page) -> None:
    """The presentation downloads as a real PowerPoint package."""
    import zipfile

    # Fetched through the browser's own session rather than navigated to: a
    # download is not a page, and goto treats it as a failure to load one.
    answer = page.request.get(
        f"{BASE}/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026")
    if not answer.ok:
        raise AssertionError(f"the deck came back {answer.status}")
    saved = str(SHOTS / "report.pptx")
    with open(saved, "wb") as file:
        file.write(answer.body())

    with zipfile.ZipFile(saved) as book:
        names = book.namelist()
        slides = [n for n in names if n.startswith("ppt/slides/slide")]
        if len(slides) < 10:
            raise AssertionError(f"the deck has {len(slides)} slides")
        if "ppt/presentation.xml" not in names or "ppt/theme/theme1.xml" not in names:
            raise AssertionError(f"the deck is missing parts: {names}")
        words = book.read("ppt/slides/slide1.xml").decode("utf-8")
        if "SIBLINE-PORT" not in words:
            raise AssertionError("the cover does not name the project")
        # It is drawn, not tabulated: the dial, the curve and the bars are all
        # shapes, and the cover and the dividers are dark.
        everything = " ".join(book.read(n).decode("utf-8") for n in slides)
        for drawn, what in (("blockArc", "the dial"), ("custGeom", "the S-curve"),
                            ("13293D", "the dark slides")):
            if drawn not in everything:
                raise AssertionError(f"the deck has no {what}")

    # And it is kept, so somebody else can see the one that went out.
    page.goto(f"{BASE}/projects/1/assistant/documents", wait_until="networkidle")
    _put_carmen_away(page)
    body = page.text_content("body")
    if "Presentation" not in body:
        raise AssertionError("the deck was not kept with the project")
    kept = page.locator("a:has-text('Open')").first.get_attribute("href")
    again = page.request.get(BASE + kept)
    if not again.ok or again.body() != answer.body():
        raise AssertionError("the kept copy is not the file that went out")
    page.screenshot(path=str(SHOTS / "48-documents.png"), full_page=True)


def _carmen_everywhere(page) -> None:
    """Carmen sits in the corner of every project page, minutes a meeting from
    a paragraph, and takes you somewhere when you ask her to."""
    page.goto(f"{BASE}/projects/1/schedule", wait_until="networkidle")
    if page.locator("#carmen-open").count() == 0:
        raise AssertionError("Carmen is not on the schedule")

    # Her own tab is the conversation already; a second copy in the corner is
    # two chats to keep track of.
    page.goto(f"{BASE}/projects/1/assistant", wait_until="networkidle")
    if page.locator("#carmen-popup").count():
        raise AssertionError("the pop-up should not be on her own tab")
    page.goto(f"{BASE}/projects/1/schedule", wait_until="networkidle")

    if page.locator("#carmen-popup:not([hidden])").count():
        raise AssertionError("she should start minimised on every page")
    face = page.locator("#carmen-open img")
    if face.count() == 0:
        raise AssertionError("the launcher should show her picture")

    _open_carmen(page)

    # Shut again with the ✕, and shut again on the next page: a chat box that
    # reappears in the corner of every tab is not a feature.
    page.click("[data-carmen-close]")
    # state="hidden": the default waits for an element to become visible, which
    # is never true of the thing this step is checking got hidden.
    page.wait_for_selector("#carmen-popup", state="hidden", timeout=4000)
    page.goto(f"{BASE}/projects/1/tasks", wait_until="networkidle")
    if page.locator("#carmen-popup:not([hidden])").count():
        raise AssertionError("she should not reopen herself on the next page")
    _open_carmen(page)

    if not os.environ.get("CLAUDE_STAND_IN"):
        page.screenshot(path=str(SHOTS / "39-carmen.png"), full_page=True)
        return

    # Minuting: a paragraph in, a numbered register out.
    popup = page.locator("#carmen-popup")
    popup.locator("textarea[name=question]").fill(
        "Minute this: we had a coordination call, the client asked about bathymetry.")
    popup.locator("button:has-text('Ask')").click()
    page.wait_for_selector("#carmen-popup .chat-staged", timeout=25000)
    staged = popup.locator(".chat-staged").last.inner_text()
    if "Minute" not in staged:
        raise AssertionError(f"minuting was not staged: {staged!r}")
    popup.locator(".chat-staged button:has-text('Apply')").click()
    page.wait_for_selector("#carmen-popup .chat-staged:has-text('Applied')", timeout=15000)
    page.screenshot(path=str(SHOTS / "39-carmen.png"), full_page=True)

    minutes = page.request.get(f"{BASE}/projects/1/minutes?filter=all").text()
    if "Bathymetry survey" not in minutes:
        raise AssertionError("the minuted item did not reach the Minutes tab")

    # And the Word export comes out on the template.
    import zipfile

    found = re.search(r'/projects/1/minutes/meetings/(\d+)"', minutes)
    if not found:
        raise AssertionError("no meeting to export")
    document = page.request.get(
        f"{BASE}/projects/1/minutes/meetings/{found.group(1)}.docx")
    saved = str(SHOTS / "minutes.docx")
    with open(saved, "wb") as file:
        file.write(document.body())
    with zipfile.ZipFile(saved) as book:
        names = book.namelist()
        for part in ("word/header1.xml", "word/footer1.xml", "word/media/logo.png"):
            if part not in names:
                raise AssertionError(f"the minutes have no {part}")
        if "Minutes of Meeting" not in book.read("word/header1.xml").decode("utf-8"):
            raise AssertionError("the letterhead is missing")
        body = book.read("word/document.xml").decode("utf-8")
        for expected in ("Items and Agreement", "Prepared by:", "Reviewed", "Issue date:"):
            if expected not in body:
                raise AssertionError(f"the minutes have no {expected!r}")

    # Taking somebody somewhere.
    page.goto(f"{BASE}/projects/1/tasks", wait_until="networkidle")
    _open_carmen(page)
    popup.locator("textarea[name=question]").fill("take me to the schedule")
    popup.locator("button:has-text('Ask')").click()
    page.wait_for_url("**/schedule", timeout=25000)
    _put_carmen_away(page)


def _sorting(page) -> None:
    """Sorting is checked as an ordering rather than against a named line: which
    deliverable happens to be worst depends on everything the run did before
    this step, and that is not what the column is for."""
    page.click("a:has-text('Progress')")
    page.wait_for_selector("text=Progress update >> visible=true", timeout=8000)
    page.click("th a:has-text('Variance')")
    page.wait_for_selector("text=All deliverables >> visible=true", timeout=8000)

    shown = page.eval_on_selector_all(
        "tbody tr td:nth-child(7)",
        "els => els.map(e => parseFloat(e.textContent.replace('%','').replace('+','')))")
    figures = [v for v in shown if v == v]                # drop anything unparsed
    if len(figures) < 5:
        raise AssertionError(f"no variance column to sort: {shown[:5]}")
    if figures != sorted(figures):
        raise AssertionError(f"worst variance should sort first: {figures[:6]}")

    page.click("th a:has-text('WBS')")
    page.wait_for_selector("text=Sec. 3.1 Marine Design >> visible=true", timeout=8000)
    numbers = [t.strip() for t in page.locator(
        "tbody tr td:nth-child(1)").all_inner_texts() if t.strip()]
    if numbers[:3] != ["1.1", "1.2", "1.3"]:
        raise AssertionError(f"WBS order is wrong: {numbers[:5]}")
    page.screenshot(path=str(SHOTS / "12-sorted.png"), full_page=True)


def _stepped_planned(page) -> None:
    """A workflow line's planned figure should read one of the step values and
    never something between. Simple lines are pro rata by time, so they are
    allowed any percentage and are excluded here."""
    values = page.eval_on_selector_all(
        "tr[data-tracking='workflow'] td:nth-child(5)",
        "els => els.map(e => e.textContent.trim())",
    )
    if not values:
        raise AssertionError("no workflow rows found to check")
    seen = {v for v in values if v.endswith("%")}
    stray = seen - {"0%", "10%", "40%", "60%", "80%", "100%"}
    if stray:
        raise AssertionError(f"planned showed values between steps: {sorted(stray)}")

    # And the simple lines really are being tracked differently.
    if page.locator("tr[data-tracking='simple']").count() == 0:
        raise AssertionError("expected some lines tracked as a simple percentage")


def _save_all(page) -> None:
    page.fill("input[name='max_revisions']", "8")
    page.click("button:has-text('Save all changes')")
    page.wait_for_selector("text=Saved — project settings >> visible=true", timeout=8000)
    if page.input_value("input[name='max_revisions']") != "8":
        raise AssertionError("the saved value did not come back")


def _print_to_pdf(page) -> None:
    """Each report tab offers a print button and carries a print-only header."""
    for tab, heading in [("Progress", "Progress update"), ("Schedule", "Schedule"),
                         ("Finance", "Finance"),
                         ("Resources", "Resources planning"),
                         ("Summarized Progress", "Summarized Progress")]:
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
    page.wait_for_selector("text=Project setup >> visible=true", timeout=8000)
    if "Locked" not in page.text_content("body"):
        raise AssertionError("the setup sheet should start locked")

    page.fill("input[name=password]", "2026")
    page.click("button:has-text('Unlock')")
    page.wait_for_selector("text=Setup sheet unlocked >> visible=true", timeout=8000)
    body = page.text_content("body")
    for expected in ("Design workflow", "IDC provided", "Maximum revisions",
                     "Rework days", "Export to Excel", "Import from Excel"):
        if expected not in body:
            raise AssertionError(f"setup is missing {expected!r}")

    # Carmen's key and her picture are set here, once, for everybody.
    for expected in ("Carmen's API key", "Her picture"):
        if expected not in body:
            raise AssertionError(f"setup is missing {expected!r}")
    if page.locator("form[action$='/assistant/face'] input[type=file]").count() == 0:
        raise AssertionError("her picture cannot be changed from setup")
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
    page.click("nav.tabs a:has-text('Schedule')")
    page.wait_for_selector("text=Dates and durations >> visible=true", timeout=8000)
    body = page.text_content("body")
    for expected in ("Programme", "Dependencies", "Duration", "Float"):
        if expected not in body:
            raise AssertionError(f"the schedule is missing {expected!r}")
    for gone in ("Late deliverables", "Behind plan"):
        if gone in body:
            raise AssertionError(f"{gone!r} belongs on the Progress tab now")
    for mark in ("Planned bar", "IDC (workflow only)", "Submission",
                 "Code A due (workflow only)", "Rework after a Code B or C", "Today"):
        if mark not in body:
            raise AssertionError(f"the legend does not say what {mark!r} is")
    if page.locator(".chart svg circle").count() == 0:
        raise AssertionError("the IDC marks are missing from the bars")
    if page.locator(".chart svg polygon").count() == 0:
        raise AssertionError("the submission and Code A stars are missing")
    if "2026" not in page.text_content(".chart"):
        raise AssertionError("the chart should name the months it covers")
    page.screenshot(path=str(SHOTS / "21-schedule.png"), full_page=True)


def _schedule_links(page) -> None:
    """Linking two lines sequences them, and moving one moves the other."""
    _schedule_page(page, "links")
    page.select_option("select[name=successor_id]", index=2)
    page.select_option("select[name=predecessor_id]", index=1)
    page.select_option("select[name=kind]", "FS")
    rows = page.locator("tr[id^='link-']").count()
    page.click("button:has-text('Link them')")
    page.wait_for_function(f"document.querySelectorAll(\"tr[id^='link-']\").length > {rows}",
                           timeout=8000)
    if page.locator("text=On the critical path").count() == 0:
        raise AssertionError("the network should name the critical path")
    if page.locator("svg path[marker-end]").count() == 0:
        raise AssertionError("the dependency arrows are missing")
    page.screenshot(path=str(SHOTS / "22-network.png"), full_page=True)


def _squeeze(page) -> None:
    """A run of the programme fitted between two dates: worked out first,
    applied only when the button under the proposal is pressed, and put back."""
    # Read the first row with the dates panel open — a row inside a folded
    # panel has no text to compare, which is not the same as not having moved.
    _schedule_page(page, "dates")
    before = page.locator("tr[id^='task-']").first.inner_text()

    def work_it_out() -> None:
        _schedule_page(page, "squeeze")
        if page.locator("select[name=from_task] option").count() < 3:
            raise AssertionError("the squeeze has no deliverables to choose from")
        page.select_option("select[name=from_task]", index=1)
        page.select_option("select[name=to_task]", index=2)
        page.fill("input[name=starts]", "31/08/2026")
        page.fill("input[name=ends]", "30/11/2026")
        page.click("button:has-text('Work it out')")
        page.wait_for_selector("text=Every duration × >> visible=true", timeout=8000)

    work_it_out()
    body = page.text_content("body")
    if "30/11/2026" not in body:
        raise AssertionError("the proposal does not say when the run finishes")
    # Every line can be held out of it, and every one shows what its Code A becomes.
    if page.locator("input[name=hold]").count() < 2:
        raise AssertionError("lines cannot be held out of the squeeze")
    if page.locator("form[action$='/schedule/squeeze'] button").count() == 0:
        raise AssertionError("the proposal offers no way to apply it")
    page.screenshot(path=str(SHOTS / "23-squeeze.png"), full_page=True)

    # Nothing has moved while the proposal is still only a proposal.
    _schedule_page(page, "dates")
    if page.locator("tr[id^='task-']").first.inner_text() != before:
        raise AssertionError("working it out must not move anything")

    # Now apply it.
    work_it_out()
    page.click("form[action$='/schedule/squeeze'] button")
    page.wait_for_selector("text=the run now finishes >> visible=true", timeout=8000)
    said = page.text_content(".flash")
    if "Squeezed" not in said or "30/11/2026" not in said:
        raise AssertionError(f"the squeeze did not report itself: {said!r}")

    _schedule_page(page, "dates")
    if page.locator("tr[id^='task-']").first.inner_text() == before:
        raise AssertionError("applying it should have moved the dates")

    # And it can be put back exactly.
    _schedule_page(page, "squeeze")
    page.click("form[action*='/schedule/restore/'] button")
    page.wait_for_selector("text=back to where they were >> visible=true", timeout=8000)
    _schedule_page(page, "dates")
    if page.locator("tr[id^='task-']").first.inner_text() != before:
        raise AssertionError("putting it back should return the dates exactly")


def _schedule_deps(page) -> None:
    """A lag and a link type change in the row; a box can be dragged; a
    dependency is removed without the page reloading."""
    _schedule_page(page, "links")
    # A second link, this one start-to-start.
    page.select_option("select[name=successor_id]", index=3)
    page.select_option("select[name=predecessor_id]", index=1)
    page.select_option("select[name=kind]", "SS")
    page.fill("input[name=lag_days]", "-5")          # work that overlaps
    rows = page.locator("tr[id^='link-']").count()
    page.click("button:has-text('Link them')")
    page.wait_for_function(f"document.querySelectorAll(\"tr[id^='link-']\").length > {rows}",
                           timeout=8000)
    if page.locator("svg path[stroke-dasharray]").count() == 0:
        raise AssertionError("a start-to-start link should draw differently")
    if "-5d" not in page.text_content("body"):
        raise AssertionError("a negative lag should be kept")

    url = page.url
    page.locator("[data-cell='link-lag']").first.click()
    page.wait_for_selector("form.cell-form input[name=lag_days]", timeout=6000)
    page.fill("form.cell-form input[name=lag_days]", "12")
    page.locator("form.cell-form input[name=lag_days]").blur()
    page.wait_for_timeout(1400)
    if page.url != url:
        raise AssertionError("changing a lag should not reload the page")
    if "12d" not in page.locator("[data-cell='link-lag']").first.inner_text():
        raise AssertionError("the lag did not stick")

    page.locator("[data-cell='link-kind']").first.click()
    page.wait_for_selector("form.cell-form select[name=kind]", timeout=6000)
    page.select_option("form.cell-form select[name=kind]", "SS")
    page.wait_for_timeout(1400)
    if "start → start" not in page.locator("[data-cell='link-kind']").first.inner_text():
        raise AssertionError("the link type did not stick")

    # Either end of the link moves in the row too, and the row redraws with the
    # deliverable it now points at.
    link = page.locator("tr[id^='link-']").first.get_attribute("id")
    end = page.locator(f"#{link} [data-cell='link-successor']")
    waits_on = page.locator(f"#{link} [data-cell='link-predecessor']").get_attribute("data-value")
    before = end.inner_text().strip()
    end.click()
    page.wait_for_selector("form.cell-form select[name=successor_id]", timeout=6000)
    choices = page.locator("form.cell-form select[name=successor_id] option")
    moved_to = next(                       # a late line: nothing yet waits on it
        choices.nth(i).get_attribute("value")
        for i in reversed(range(choices.count()))
        if choices.nth(i).get_attribute("value") != waits_on
    )
    page.select_option("form.cell-form select[name=successor_id]", moved_to)
    page.wait_for_timeout(1400)
    if page.url != url:
        raise AssertionError("moving an end of a link should not reload the page")
    end = page.locator(f"#{link} [data-cell='link-successor']")
    if end.inner_text().strip() == before:
        raise AssertionError(f"the link still waits on {before!r}")
    if end.get_attribute("data-value") != moved_to:
        raise AssertionError("the cell did not take the deliverable it now points at")

    # A link onto itself is refused, and says so without losing the page.
    end.click()
    page.wait_for_selector("form.cell-form select[name=successor_id]", timeout=6000)
    page.select_option("form.cell-form select[name=successor_id]", waits_on)
    page.wait_for_selector(".flash.error", timeout=6000)
    if page.url != url:
        raise AssertionError("a refused change should not throw the page away")
    if page.locator(f"#{link} [data-cell='link-successor']").get_attribute("data-value") != moved_to:
        raise AssertionError("a refused change should leave the cell as it was")

    page.reload(wait_until="networkidle")
    if page.locator(f"#{link} [data-cell='link-successor']").inner_text().strip() == before:
        raise AssertionError("the moved end did not survive a reload")

    # A box can be dragged out of the way, and stays there.
    box = page.locator(".net-node.movable").first
    box.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    before = (box.get_attribute("data-x"), box.get_attribute("data-y"))
    place = box.bounding_box()
    page.mouse.move(place["x"] + place["width"] / 2, place["y"] + place["height"] / 2)
    page.mouse.down()
    page.mouse.move(place["x"] + place["width"] / 2 + 160,
                    place["y"] + place["height"] / 2 + 90, steps=10)
    page.mouse.up()
    page.wait_for_timeout(1200)

    moved = page.locator(".net-node.movable").first
    if (moved.get_attribute("data-x"), moved.get_attribute("data-y")) == before:
        raise AssertionError("the box did not move")
    page.reload(wait_until="networkidle")
    kept = page.locator(".net-node.movable").first
    if (kept.get_attribute("data-x"), kept.get_attribute("data-y")) == before:
        raise AssertionError("the box did not stay where it was put")
    page.screenshot(path=str(SHOTS / "23-dependencies.png"), full_page=True)

    # Removing one takes its row with it, and nothing reloads.
    rows = page.locator("tr[id^='link-']").count()
    url = page.url
    page.locator("form[data-live-remove] button").first.click()
    page.wait_for_timeout(1400)
    if page.url != url:
        raise AssertionError("removing a dependency should not reload the page")
    if page.locator("tr[id^='link-']").count() != rows - 1:
        raise AssertionError("the row was not removed")

    # The dependencies go out to Excel and come back.
    card = _card(page, "Dependencies")
    with page.expect_download(timeout=10000) as download:
        card.locator("a:has-text('Export to Excel')").click()
    workbook = str(SHOTS / "dependencies.xlsx")
    download.value.save_as(workbook)
    if not download.value.suggested_filename.endswith(".xlsx"):
        raise AssertionError("the dependencies did not download as a workbook")

    card.locator("input[name=workbook]").set_input_files(workbook)
    card.locator("button:has-text('Import')").click()
    page.wait_for_selector("text=imported >> visible=true", timeout=8000)
    if "skipped" in page.text_content("body"):
        raise AssertionError("its own export should import without a complaint")

    # And Tidy up puts the boxes back under the automatic layout.
    page.click("button:has-text('Tidy up')")
    page.wait_for_timeout(1400)
    tidied = page.locator(".net-node.movable").first
    if (tidied.get_attribute("data-x"), tidied.get_attribute("data-y")) != ("16", "16"):
        raise AssertionError("tidy up should return the boxes to the layout")


def _schedule_amend(page) -> None:
    _schedule_page(page, "dates")
    before = page.locator("#submission-1").inner_text().strip()
    url = page.url
    page.locator("#duration-1 .cell-open").click()
    page.wait_for_selector("form.cell-form input[name=duration_days]", timeout=8000)
    page.fill("form.cell-form input[name=duration_days]", "45")
    page.locator("form.cell-form input[name=duration_days]").blur()
    page.wait_for_timeout(1600)

    if page.url != url:
        raise AssertionError("amending the plan should not reload the page")
    after = page.locator("#submission-1").inner_text().strip()
    if after == before:
        raise AssertionError(f"the finish did not follow the duration: {before} -> {after}")
    if page.locator("#duration-1 .cell-open").count() != 1:
        raise AssertionError("the cell must stay clickable after a change")
    if "45d" not in page.locator("#duration-1").inner_text():
        raise AssertionError("the duration did not stick")


def _budget(page) -> None:
    page.click("nav.tabs a:has-text('Finance')")
    page.wait_for_selector("text=Hours against budget by trade >> visible=true", timeout=8000)
    page.wait_for_selector(".chart svg", timeout=8000)
    page.screenshot(path=str(SHOTS / "06-budget.png"), full_page=True)


def _resources(page) -> None:
    """The budget as a rota: a ceiling per trade, hours per week, and people.

    Booked hours reach this tab too, so the step runs after the hours are
    booked and checks the tab has seen them.
    """
    page.click("nav.tabs a:has-text('Resources')")
    page.wait_for_selector("text=Resources planning >> visible=true", timeout=8000)
    _expect_all(page, ["Held back as margin", "Engineers per week",
                       "Ceiling per deliverable", "Week by week"])
    if page.locator(".chart svg").count() < 2:
        raise AssertionError("both charts should draw")

    # The week table is the part somebody staffs from, so it has to have weeks
    # in it and each of them a number of people.
    weeks = page.locator(".card:has(h2:text-is('Week by week'))")
    if not weeks.locator("details[open]").count():
        weeks.locator(".panel-summary").click()
    rows = weeks.locator("tbody tr")
    if rows.count() < 4:
        raise AssertionError(f"only {rows.count()} weeks planned")
    first = rows.nth(0).text_content()
    if " h" not in first:
        raise AssertionError(f"a week with no hours: {first!r}")

    # A column per trade, on both tables, rather than a list crammed in a cell.
    for card, table in (("Week by week", weeks),
                        ("Ceiling per deliverable",
                         page.locator(".card:has(h2:text-is('Ceiling per deliverable'))"))):
        headings = table.locator("thead th").all_text_contents()
        for trade in ("Marine", "Geotechnical", "Utilities"):
            if not any(trade in head for head in headings):
                raise AssertionError(f"{card} has no {trade} column: {headings}")

    page.screenshot(path=str(SHOTS / "35-resources.png"), full_page=True)


def _resources_staffing(page) -> None:
    """The one figure on the tab somebody sets rather than reads.

    It saves as it is typed, the week's total follows it because the total is
    the sum of its trades, and the hours the week is allowed do not move — that
    last part is the whole point of letting somebody set it.
    """
    page.click("nav.tabs a:has-text('Resources')")
    page.wait_for_selector("text=Resources planning >> visible=true", timeout=8000)
    weeks = page.locator(".card:has(h2:text-is('Week by week'))")
    if not weeks.locator("details[open]").count():
        weeks.locator(".panel-summary").click()

    row = page.locator("tr[data-week-row]").first
    box = row.locator(".heads").first
    box.scroll_into_view_if_needed()
    hours_before = row.locator("td").nth(1).text_content().strip()
    people_before = int(row.locator("[data-week-people]").inner_text())
    was = int(box.input_value())

    box.fill(str(was + 5))
    page.wait_for_function(
        "([row, want]) => row.querySelector('[data-week-people]').textContent.trim() === want",
        arg=[row.element_handle(), str(people_before + 5)], timeout=8000)

    if "by-hand" not in (box.get_attribute("class") or ""):
        raise AssertionError("a hand-set figure should not read as arithmetic")
    if row.locator("td").nth(1).text_content().strip() != hours_before:
        raise AssertionError("setting the engineers must not move the hours")
    if not row.locator("[data-week-wanted]").is_visible():
        raise AssertionError("the figure the plan asked for should be shown beside it")

    page.screenshot(path=str(SHOTS / "36-staffing.png"), full_page=True)

    # Reload rather than trusting the page's own redraw: the point is that it
    # was saved, not that the number changed on screen.
    page.reload(wait_until="networkidle")
    if not weeks.locator("details[open]").count():
        weeks.locator(".panel-summary").click()
    again = page.locator("tr[data-week-row]").first.locator(".heads").first
    if int(again.input_value()) != was + 5:
        raise AssertionError(f"not saved: {again.input_value()} rather than {was + 5}")

    # Cleared, it goes back to what the plan asked for.
    again.fill("")
    page.wait_for_timeout(900)
    page.reload(wait_until="networkidle")
    if not weeks.locator("details[open]").count():
        weeks.locator(".panel-summary").click()
    back = page.locator("tr[data-week-row]").first.locator(".heads").first
    if "by-hand" in (back.get_attribute("class") or ""):
        raise AssertionError("clearing the box should hand the week back to the plan")


def _resources_sorting(page) -> None:
    """Both tables sort on every column, the trades included, and they sort
    independently — ordering the weeks must not reorder the deliverables."""
    page.goto(f"{BASE}/projects/1/resources", wait_until="networkidle")
    lines = page.locator(".card:has(h2:text-is('Ceiling per deliverable'))")
    if not lines.locator("details[open]").count():
        lines.locator(".panel-summary").click()

    def wbs_column() -> list:
        return [cell.strip() for cell in
                lines.locator("tbody tr td:first-child").all_text_contents()]

    lines.locator("thead a.sort-link", has_text="WBS").first.click()
    page.wait_for_selector("text=Ceiling per deliverable >> visible=true", timeout=8000)
    if not lines.locator("details[open]").count():
        lines.locator(".panel-summary").click()
    climbing = wbs_column()

    lines.locator("thead a.sort-link", has_text="WBS").first.click()
    page.wait_for_selector("text=Ceiling per deliverable >> visible=true", timeout=8000)
    if not lines.locator("details[open]").count():
        lines.locator(".panel-summary").click()
    falling = wbs_column()

    if climbing != list(reversed(falling)):
        raise AssertionError("WBS does not sort both ways")

    # A trade's own column, on the weeks table, leaves the deliverables alone.
    weeks = page.locator(".card:has(h2:text-is('Week by week'))")
    weeks.locator("thead a.sort-link", has_text="Marine").first.click()
    page.wait_for_selector("text=Week by week >> visible=true", timeout=8000)
    if not lines.locator("details[open]").count():
        lines.locator(".panel-summary").click()
    if wbs_column() != falling:
        raise AssertionError("sorting the weeks reordered the deliverables")


def _resources_reserve(page) -> None:
    """A deliverable that comes back Code A first time never needed its comments
    reserve, and those hours are a saving that trade earned."""
    page.goto(f"{BASE}/projects/1/resources", wait_until="networkidle")
    _expect_all(page, ["Held for comments", "Released by a clean Code A",
                       "Spent answering comments", "Savings from finishing cleanly"])

    def released() -> str:
        return page.locator(".tile:has-text('Released by a clean Code A') .tile-value"
                            ).text_content().strip()

    before = released()

    # Take a line all the way to Code A on the Progress tab, without comments —
    # the one thing that turns a held reserve into a saving.
    page.goto(f"{BASE}/projects/1/tasks", wait_until="networkidle")
    row = page.locator("tr", has_text="Review & consolidate available assessment").first
    row.locator(".cell-open[data-cell]").first.click()
    page.wait_for_selector("form.cell-form select[name=status_key]", timeout=8000)
    page.select_option("form.cell-form select[name=status_key]", label="Code A received — 100%")
    page.wait_for_timeout(1400)

    page.goto(f"{BASE}/projects/1/resources", wait_until="networkidle")
    if released() == before:
        raise AssertionError(f"a clean Code A released nothing: still {before}")
    # Named before the button is pressed as well as after: deciding whether to
    # redistribute means seeing where the hours came from first.
    body = page.text_content("body")
    if "Code A first time, so the reserve was never needed" not in body:
        raise AssertionError("the savings are not explained")
    if "held as a saving" not in body:
        raise AssertionError("a saving nobody has shared out should say so")

    page.click("button:has-text('Redistribute the savings')")
    page.wait_for_selector("text=Savings redistributed >> visible=true", timeout=8000)
    body = page.text_content("body")
    if "Stop redistributing" not in body:
        raise AssertionError("redistribution did not stay on")
    if "open deliverable" not in body:
        raise AssertionError("the notes do not say where the savings went")
    page.screenshot(path=str(SHOTS / "37-savings.png"), full_page=True)


def _resources_margin(page) -> None:
    """Every figure on the tab hangs off two numbers in Setup, so moving one of
    them has to move the tab — and moving it back has to put it back."""
    def ceiling() -> float:
        page.click("nav.tabs a:has-text('Resources')")
        page.wait_for_selector("text=Held back as margin >> visible=true", timeout=8000)
        words = page.locator(".tile:has-text('Held back as margin') .tile-value").text_content()
        return float(words.replace(",", "").replace("h", "").strip())

    held_at_12 = ceiling()

    page.click("nav.tabs a:has-text('Setup')")
    page.wait_for_selector("input[name=target_margin_pct]", timeout=8000)
    if page.locator("input[name=password]").count():
        page.fill("input[name=password]", "2026")
        page.click("button:has-text('Unlock')")
        page.wait_for_selector("input[name=target_margin_pct]:not([disabled])", timeout=8000)
    page.fill("input[name=target_margin_pct]", "24")
    page.click("button:has-text('Save all')")
    page.wait_for_selector("text=Saved >> visible=true", timeout=8000)

    held_at_24 = ceiling()
    if not (1.9 < held_at_24 / max(held_at_12, 1e-9) < 2.1):
        raise AssertionError(f"doubling the margin should double what is held back: "
                             f"{held_at_12} then {held_at_24}")

    page.click("nav.tabs a:has-text('Setup')")
    page.wait_for_selector("input[name=target_margin_pct]", timeout=8000)
    page.fill("input[name=target_margin_pct]", "12")
    page.click("button:has-text('Save all')")
    page.wait_for_selector("text=Saved >> visible=true", timeout=8000)


def _book_hours(page) -> None:
    """The hours are booked on the same tab as the budget they are charged to:
    reading a figure on one tab and going to another to see what made it is how
    a number stops being checked."""
    page.click("nav.tabs a:has-text('Finance')")
    page.wait_for_selector("text=Book hours >> visible=true", timeout=8000)
    page.select_option("select[name=trade_id]", label="Geotechnical")
    page.fill("input[name=hours]", "36")
    page.fill("input[name=description]", "Borehole data review")
    page.click("button:has-text('Book hours')")
    page.wait_for_selector("text=Booked 36 hours >> visible=true", timeout=8000)
    body = page.text_content("body")
    if "Borehole data review" not in body:
        raise AssertionError("entry not listed")
    if "36 h" not in body:
        raise AssertionError("booked hours did not reach the budget figures on the same tab")
    page.screenshot(path=str(SHOTS / "07-timesheet.png"), full_page=True)


def _period(page) -> None:
    """A month is not only percentages: half of what happened is in the
    register, so what closed and what was raised are on the same page."""
    page.click("nav.tabs a:has-text('Summarized Progress')")
    page.wait_for_selector("h1:has-text('Summarized Progress')", timeout=8000)
    page.wait_for_selector("text=Earned in period by trade >> visible=true")

    body = page.text_content("body")
    for expected in ("Actions closed in this period", "Actions raised in this period",
                     "Still open at"):
        if expected not in body:
            raise AssertionError(f"the report does not carry {expected!r}")
    page.screenshot(path=str(SHOTS / "08-period.png"), full_page=True)


def _with_client(page) -> None:
    """Submitted and waiting for the Code A: the work is out of the door, so
    the line reads green rather than late, however long the client takes."""
    page.goto(f"{BASE}/projects/1/tasks?data_date=31/12/2026", wait_until="networkidle")
    _put_carmen_away(page)

    # Moved to submitted through the cell on the row, as anybody would. The
    # control saves as soon as the step is chosen; no button.
    row = page.locator("#task-2")
    row.locator(".cell-open[data-cell]").first.click()
    page.wait_for_selector("form.cell-form select[name=status_key]", timeout=8000)
    page.select_option("form.cell-form select[name=status_key]",
                       label="Submitted to client — 80%")
    page.wait_for_function(
        "() => { const line = document.getElementById('task-2');"
        " return line && line.innerText.includes('With client'); }", timeout=8000)

    line = row.inner_text()
    if "late" in line.lower():
        raise AssertionError(f"a line with the client should not read as late: {line!r}")
    if "Behind plan" in line:
        raise AssertionError("a line with the client should not read as behind plan")

    # And it can be filtered to.
    page.goto(f"{BASE}/projects/1/tasks?filter=client&data_date=31/12/2026",
              wait_until="networkidle")
    _put_carmen_away(page)
    if "With client" not in page.text_content("body"):
        raise AssertionError("the With client filter shows nothing")
    page.screenshot(path=str(SHOTS / "47-with-client.png"), full_page=True)


def _minutes_capture(page) -> None:
    """The roster is typed once, then ticked; items carry an owner and an impact."""
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("text=Attendance list >> visible=true", timeout=8000)

    for name, org, role in [("Ahmed Mitwally", "Dar", "Project manager"),
                            ("Client Rep", "Sibline Port Authority", "Design manager")]:
        roster = page.locator("form", has=page.locator("button:has-text('Add attendee')"))
        roster.locator("input[name=name]").fill(name)
        roster.locator("input[name=organisation]").fill(org)
        roster.locator("input[name=job_title]").fill(role)
        roster.locator("button:has-text('Add attendee')").click()
        page.wait_for_selector(f"text={name} added to the attendance list", timeout=8000)

    meeting_form = page.locator("form", has=page.locator("button:has-text('Add meeting')"))
    meeting_form.locator("input[name=ref]").fill("MOM-01")
    meeting_form.locator("input[name=title]").fill("Weekly design coordination")
    meeting_form.locator("input[name=meeting_date]").fill("03/09/2026")
    meeting_form.locator("input[name=location]").fill("Site office")
    meeting_form.locator("button:has-text('Add meeting')").click()
    page.wait_for_selector("text=tick who attended >> visible=true", timeout=8000)

    # Everyone is invited by default; untick one to show apologies.
    boxes = page.locator("input[name=present]")
    if boxes.count() != 2:
        raise AssertionError(f"expected a tick box per attendee, found {boxes.count()}")
    boxes.nth(1).uncheck()
    page.fill("input[name=chaired_by]", "Ahmed Mitwally")
    page.fill("input[name=next_date]", "10/09/2026")
    page.click("button:has-text('Save meeting')")
    page.wait_for_selector("text=Meeting saved >> visible=true", timeout=8000)
    if "Apologies" not in page.text_content("body"):
        raise AssertionError("the attendee who was unticked should show apologies")

    for subject, agreement, impact, due, owner in [
        ("Quay wall levels", "Marine to reissue the layout", "Time", "10/09/2026", "MR"),
        ("Additional bathymetric survey", "Client to confirm the budget", "Cost", "01/08/2026", "Client"),
    ]:
        form = page.locator("form", has=page.locator("button:has-text('Add item')"))
        form.locator("input[name=subject]").fill(subject)
        form.locator("textarea[name=agreement]").fill(agreement)
        form.locator("select[name=impact]").select_option(label=impact)
        form.locator("input[name=due_date]").fill(due)
        form.locator("select[name=owner_code]").select_option(owner)
        # An item can bear on more than one trade at a time.
        form.locator("input[name=trade_ids]").first.check()
        form.locator("input[name=trade_ids]").nth(1).check()
        form.locator("button:has-text('Add item')").click()
        page.wait_for_selector("text=Item added >> visible=true", timeout=8000)

    body = page.text_content("body")
    for expected in ("Quay wall levels", "Marine to reissue the layout", "SIBLINE-PORT",
                     "MR", "Marine", "Geotechnical"):
        if expected not in body:
            raise AssertionError(f"the minutes are missing {expected!r}")
    page.screenshot(path=str(SHOTS / "14-meeting.png"), full_page=True)


def _minutes_filters(page) -> None:
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    body = page.text_content("body")
    if "Quay wall levels" not in body:
        raise AssertionError("open items should be shown by default")
    if "MOM-01" not in body:
        raise AssertionError("the meeting reference did not save")

    page.click(".chips a:has-text('Overdue')")
    page.wait_for_timeout(400)
    body = page.text_content("body")
    if "Additional bathymetric survey" not in body or "Quay wall levels" in body:
        raise AssertionError("the overdue filter did not narrow the register")

    page.click(".chips a:has-text('All items')")
    page.wait_for_timeout(300)
    page.fill("input[name=q]", "quay")
    page.click("button:has-text('Apply')")
    page.wait_for_timeout(400)
    body = page.text_content("body")
    if "Quay wall levels" not in body or "bathymetric" in body:
        raise AssertionError("the keyword search did not narrow the register")

    page.click("a:has-text('Clear')")
    page.wait_for_timeout(300)
    page.click("th a:has-text('Due')")
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "15-minutes.png"), full_page=True)


def _minutes_word(page) -> None:
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    with page.expect_download(timeout=10000) as download:
        page.click("a:has-text('Export Word')")
    name = download.value.suggested_filename
    if not name.endswith(".docx"):
        raise AssertionError(f"unexpected download: {name}")

    page.click("table a:has-text('Weekly design coordination')")
    page.wait_for_selector("text=Items and agreements >> visible=true", timeout=8000)
    with page.expect_download(timeout=10000) as download:
        page.click("a:has-text('Export Word')")
    if not download.value.suggested_filename.endswith(".docx"):
        raise AssertionError("the minutes did not download as a Word document")


def _minutes_reorder(page) -> None:
    """An item's number is its position, so moving it renumbers both rows."""
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    page.click("table a:has-text('Weekly design coordination')")
    page.wait_for_selector("text=Items and agreements >> visible=true", timeout=8000)

    rows = page.locator("tbody tr:has(button[title='Move down'])")
    before = [rows.nth(i).text_content() for i in range(rows.count())]
    if len(before) != 2 or "Quay wall levels" not in before[0]:
        raise AssertionError(f"unexpected starting order: {before}")
    if "1.1" not in before[0] or "1.2" not in before[1]:
        raise AssertionError("items should start numbered 1.1 and 1.2")

    # The first item cannot go up and the last cannot go down.
    if not page.locator("button[title='Move up']").first.is_disabled():
        raise AssertionError("the first item should not be movable up")
    if not page.locator("button[title='Move down']").last.is_disabled():
        raise AssertionError("the last item should not be movable down")

    page.locator("button[title='Move down']").first.click()
    # The move happens where it stands, so what is waited for is the row
    # changing rather than a page arriving.
    page.wait_for_function(
        "() => { const row = document.querySelector('tbody[data-items-table] tr[id^=item-]');"
        " return row && row.innerText.includes('Additional bathymetric survey'); }",
        timeout=8000)
    rows = page.locator("tbody tr:has(button[title='Move down'])")
    after = [rows.nth(i).text_content() for i in range(rows.count())]
    if "Additional bathymetric survey" not in after[0] or "1.1" not in after[0]:
        raise AssertionError(f"the moved item did not take number 1.1: {after}")
    if "Quay wall levels" not in after[1] or "1.2" not in after[1]:
        raise AssertionError(f"the swapped item did not take number 1.2: {after}")
    page.screenshot(path=str(SHOTS / "17-reordered.png"), full_page=True)

    page.locator("button[title='Move up']").last.click()      # put it back
    page.wait_for_selector("text=Items and agreements >> visible=true", timeout=8000)


def _minutes_edit_in_place(page) -> None:
    """Edit opens the form where it stands — no round trip, no jump."""
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    page.click("table a:has-text('Weekly design coordination')")
    page.wait_for_selector("text=Items and agreements >> visible=true", timeout=8000)

    row = page.locator("tr", has_text="Quay wall levels").first
    item_id = row.get_attribute("id").split("-")[1]
    editor = page.locator(f"#edit-{item_id}")
    if editor.is_visible():
        raise AssertionError("the edit form should start closed")

    url_before = page.url
    row.locator("a:has-text('Edit')").click()
    editor.wait_for(state="visible", timeout=4000)
    if page.url != url_before:
        raise AssertionError("editing should not navigate away from the page")

    box = editor.locator("textarea[name=agreement]")
    if not box.is_visible():
        raise AssertionError("the agreement should be a text area with room to write")
    if box.bounding_box()["height"] < 60:
        raise AssertionError("the writing box is too small to read back before saving")

    box.fill("Marine to reissue the layout with the revised levels agreed today")
    editor.locator("button:has-text('Save item')").click()
    page.wait_for_selector("text=Item saved >> visible=true", timeout=8000)
    if "revised levels agreed today" not in page.text_content("body"):
        raise AssertionError("the edited agreement did not save")
    page.screenshot(path=str(SHOTS / "18-edit-in-place.png"), full_page=True)


def _minutes_cells(page) -> None:
    """Owner, trades, affects and the date are changed in the row itself."""
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    row = page.locator("tr", has_text="Quay wall levels").first
    item_id = row.get_attribute("id").split("-")[1]
    url_before = page.url

    # Owner: click the cell, pick another party.
    row.locator("[data-cell='owner']").click()
    page.wait_for_selector(f"#owner-{item_id} select", timeout=4000)
    page.select_option(f"#owner-{item_id} select", "PMC")
    page.wait_for_selector(f"#owner-{item_id} .cell-open:has-text('PMC')", timeout=6000)
    if page.url != url_before:
        raise AssertionError("changing a field should not reload the page")

    # Affects: the same, and the row's wording follows.
    row.locator("[data-cell='impact']").click()
    page.wait_for_selector(f"#impact-{item_id} select", timeout=4000)
    page.select_option(f"#impact-{item_id} select", "both")
    page.wait_for_selector(f"#impact-{item_id} .cell-open:has-text('Time & cost')", timeout=6000)

    # Trades: tick another one; the cell lists them all.
    row.locator("[data-cell='trades']").click()
    page.wait_for_selector(f"#trades-{item_id} input[type=checkbox]", timeout=4000)
    page.locator(f"#trades-{item_id} input[type=checkbox]").nth(2).check()
    page.wait_for_timeout(900)
    listed = page.text_content(f"#trades-{item_id}")
    if "Marine Structures" not in listed:
        raise AssertionError(f"the trade cell did not take the new trade: {listed!r}")

    # The date, and the status badge that reads on it.
    row.locator("[data-cell='due']").click()
    page.wait_for_selector(f"#due-{item_id} input", timeout=4000)
    page.fill(f"#due-{item_id} input", "01/01/2020")
    page.locator(f"#due-{item_id} input").blur()
    page.wait_for_selector(f"#status-{item_id}:has-text('overdue')", timeout=6000)

    page.screenshot(path=str(SHOTS / "20-cells.png"), full_page=True)

    # And it really was written, not just drawn.
    page.reload(wait_until="networkidle")
    body = page.text_content("body")
    for expected in ("PMC", "Time & cost", "Marine Structures", "01/01/2020"):
        if expected not in body:
            raise AssertionError(f"{expected!r} did not survive a reload")


def _minutes_calendar(page) -> None:
    """Clicking a date field opens a calendar that writes back dd/mm/yyyy."""
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)

    field = page.locator("form input[name=due_date]").first
    field.click()
    page.wait_for_selector(".calendar", state="visible", timeout=4000)

    month = page.text_content(".cal-month")
    page.click(".cal-nav[data-step='1']")
    if page.text_content(".cal-month") == month:
        raise AssertionError("the next-month arrow did not move the calendar")
    page.click(".cal-nav[data-step='-1']")

    page.locator(".cal-day:not(.outside)").nth(14).click()
    page.wait_for_selector(".calendar", state="hidden", timeout=4000)
    value = field.input_value()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        raise AssertionError(f"the calendar wrote {value!r}, not dd/mm/yyyy")
    if not value.startswith("15/"):
        raise AssertionError(f"the fifteenth of the month should give 15/..., got {value}")

    # Typing still works, and the field is not a native picker.
    field.fill("07/10/2026")
    if page.locator("input[type=date]").count():
        raise AssertionError("a native date picker would follow the machine's locale")
    page.screenshot(path=str(SHOTS / "19-calendar.png"), full_page=True)


def _minutes_agenda(page) -> None:
    page.click("nav.tabs a:has-text('Minutes')")
    page.wait_for_selector("h1:has-text('Minutes of meeting')", timeout=8000)
    page.click("a:has-text('Next-meeting agenda')")
    page.wait_for_selector("text=Agenda >> visible=true", timeout=8000)
    body = page.text_content("body")
    for expected in ("MR", "Client", "Quay wall levels", "Additional bathymetric survey"):
        if expected not in body:
            raise AssertionError(f"the agenda is missing {expected!r}")
    page.screenshot(path=str(SHOTS / "16-agenda.png"), full_page=True)


def _dark(page) -> None:
    page.click("a:has-text('Dashboard')")
    page.wait_for_selector("text=Progress S-curve >> visible=true", timeout=8000)
    page.evaluate("localStorage.setItem('pm-theme','dark');document.documentElement.setAttribute('data-theme','dark')")
    page.wait_for_timeout(500)
    page.screenshot(path=str(SHOTS / "10-dashboard-dark.png"), full_page=True)


def _live(page) -> None:
    """A second window picks up a change on its own, without a refresh."""
    other = page.context.browser.new_context()
    watcher = other.new_page()
    watcher.goto(f"{BASE}/login", wait_until="networkidle")
    watcher.fill("input[name=email]", EMAIL)
    watcher.fill("input[name=password]", PASSWORD)
    watcher.click("button[type=submit]")
    watcher.wait_for_selector("text=Portfolio", timeout=8000)
    watcher.goto(f"{BASE}/projects/1/schedule?panel=dates", wait_until="networkidle")
    before = watcher.locator("#duration-1").inner_text().strip()

    _schedule_page(page, "dates")
    page.locator("#duration-1 .cell-open").click()
    page.wait_for_selector("form.cell-form input[name=duration_days]", timeout=8000)
    page.fill("form.cell-form input[name=duration_days]", "28")
    page.locator("form.cell-form input[name=duration_days]").blur()
    page.wait_for_timeout(1500)

    watcher.wait_for_timeout(20000)          # the live check runs every 15 seconds
    after = watcher.locator("#duration-1").inner_text().strip()
    other.close()
    if after == before:
        raise AssertionError(f"the other window did not pick the change up: {before} -> {after}")


def _backups(page) -> None:
    """Everything in one file, and a page that says whether it is happening."""
    page.goto(f"{BASE}/backups", wait_until="networkidle")
    body = page.text_content("body")
    for expected in ("Backups", "Google Drive", "Every night", "python run.py backup",
                     "Putting one back", "Connect Google Drive", "/backups/connected"):
        if expected not in body:
            raise AssertionError(f"the backups page does not mention {expected!r}")

    # It downloads as a zip holding the database.
    with page.expect_download(timeout=15000) as download:
        page.click("a:has-text('Download a copy')")
    saved = str(SHOTS / "backup.zip")
    download.value.save_as(saved)

    import zipfile

    with zipfile.ZipFile(saved) as book:
        if "project-control.sqlite3" not in book.namelist():
            raise AssertionError(f"the backup holds {book.namelist()}")
        if not book.read("project-control.sqlite3").startswith(b"SQLite format 3\x00"):
            raise AssertionError("what came down is not a database")

    # Taking one says what happened rather than pretending.
    page.click("button:has-text('Back up now')")
    page.wait_for_selector(".flash", timeout=10000)
    said = page.locator(".flash").last.inner_text()
    if "not connected" not in said and "Drive" not in said:
        raise AssertionError(f"the backup said {said!r}")
    if page.locator("tbody tr").count() == 0:
        raise AssertionError("the run should be written down whether or not it worked")

    # The nightly hour is kept in a real time zone and converted, so the page
    # can say what it is in UTC — which is what a scheduler has to be told.
    page.select_option("select[name=hour]", "0")
    page.select_option("select[name=zone]", "Africa/Cairo")
    page.check("input[name=auto]")
    page.click("button:has-text('Save the schedule')")
    page.wait_for_selector(".flash", timeout=8000)
    said = page.locator(".flash").last.inner_text()
    if "00:00 Africa/Cairo" not in said or "UTC" not in said:
        raise AssertionError(f"the schedule was saved as {said!r}")
    page.screenshot(path=str(SHOTS / "35-backups.png"), full_page=True)


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
