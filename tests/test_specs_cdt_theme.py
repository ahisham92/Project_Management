"""THEMIS wears the CDT theme (the web port of the CDT SDK); the other apps do not."""


def test_themis_pages_load_the_cdt_theme(signed_in):
    page = signed_in.get("/specs/").get_data(as_text=True)
    assert "cdt/cdt.css" in page and "cdt/cdt.js" in page
    assert "cdt-brand" in page          # the brand is set before the first paint


def test_other_apps_keep_their_own_look(signed_in):
    page = signed_in.get("/portfolio/", follow_redirects=True).get_data(as_text=True)
    assert "cdt/cdt.css" not in page and "cdt/cdt.js" not in page


def test_the_kit_is_served(client):
    for name in ("cdt/cdt.css", "cdt/cdt.js"):
        r = client.get("/static/" + name)
        assert r.status_code == 200
        r.close()
