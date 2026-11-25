"""The CDT web kit: the CDT SDK's theme and controls, on every page.

The SDK itself is WPF; what the site carries is its port (static/cdt). What is
worth pinning down is that every door loads it, after the door's own styles,
that the account menu carries the theme and accent switches, and that the
"Controls and colours" page shows the controls working.
"""

from __future__ import annotations


def text(response) -> str:
    return response.get_data(as_text=True)


def test_every_door_loads_the_kit_last(signed_in):
    for path in ("/", "/projects", "/crs/", "/specs/", "/marinetwin/"):
        page = text(signed_in.get(path))
        assert '<html lang="en" class="cdt">' in page, path
        assert "cdt/cdt.css" in page and "cdt/cdt.js" in page, path
        # after any door stylesheet, so the palette and the control states win
        for door_css in ("pm.css", "themis.css", "marinetwin.css"):
            if door_css in page:
                assert page.index(door_css) < page.index("cdt/cdt.css"), (path, door_css)


def test_the_account_menu_switches_theme_and_accent(signed_in):
    page = text(signed_in.get("/"))
    assert 'data-cdt-dropdown' in page
    for value in ("system", "light", "dark"):
        assert f'data-cdt-theme="{value}"' in page
    assert 'data-cdt-brand="dar"' in page and 'data-cdt-brand="cdt"' in page
    assert "Sign out" in page


def test_the_kit_page_shows_every_control(signed_in):
    response = signed_in.get("/kit")
    assert response.status_code == 200
    page = text(response)
    for needle in ("cdt-infobar", "cdt-steps", "cdt-util", "cdt-empty", "data-cdt-filter",
                   "trade-picker", 'data-unit="mm"', "cdt-switch", "cdt-dot", "cdt-outcome"):
        assert needle in page, needle


def test_the_kit_page_is_not_open_to_a_stranger(client):
    response = client.get("/kit")
    assert response.status_code in (302, 303)


def test_the_sign_in_page_wears_the_theme_too(client):
    page = text(client.get("/login"))
    assert 'class="cdt"' in page and "cdt/cdt.css" in page
