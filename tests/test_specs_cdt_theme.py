"""THEMIS wears its own port of the CDT SDK (cdt/themis-cdt.*); the other doors wear the site-wide one (cdt/cdt.*)."""


def test_themis_pages_load_the_cdt_theme(signed_in):
    page = signed_in.get("/specs/").get_data(as_text=True)
    assert "cdt/themis-cdt.css" in page and "cdt/themis-cdt.js" in page
    assert "cdt/cdt.css" not in page and "cdt/cdt.js" not in page
    assert "cdt-brand" in page          # the brand is set before the first paint


def test_other_apps_keep_their_own_look(signed_in):
    page = signed_in.get("/portfolio/", follow_redirects=True).get_data(as_text=True)
    assert "cdt/themis-cdt.css" not in page and "cdt/themis-cdt.js" not in page


def test_the_kit_is_served(client):
    for name in ("cdt/themis-cdt.css", "cdt/themis-cdt.js", "cdt/cdt.css", "cdt/cdt.js"):
        r = client.get("/static/" + name)
        assert r.status_code == 200
        r.close()
