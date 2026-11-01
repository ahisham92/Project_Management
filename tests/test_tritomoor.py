"""TritoMoor, the eighth door: one self-contained page behind the one sign-in."""

from __future__ import annotations


def text(response) -> str:
    return response.get_data(as_text=True)


def make(signed_in, username="sara", programs=("pm",), password="longenough1"):
    return signed_in.post("/admin/users", data={
        "username": username, "password": password, "name": "Sara", "programs": list(programs)})


def test_the_door_is_on_the_front_page(signed_in):
    page = text(signed_in.get("/"))
    assert "TritoMoor" in page
    assert 'href="/tritomoor/"' in page
    assert 'class="door" href="/tritomoor/"' in page


def test_the_program_is_served_whole_with_a_way_back(signed_in):
    answer = signed_in.get("/tritomoor/")
    assert answer.status_code == 200
    page = text(answer)
    assert "<title>TritoMoor" in page
    assert "All applications" in page
    assert page.rstrip().endswith("</html>")


def test_the_bare_address_goes_to_the_page(signed_in):
    answer = signed_in.get("/tritomoor")
    assert answer.status_code in (301, 302, 308)
    assert answer.headers["Location"].endswith("/tritomoor/")


def test_a_stranger_is_sent_to_sign_in(client):
    answer = client.get("/tritomoor/")
    assert answer.status_code in (301, 302)
    assert "/login" in answer.headers["Location"]


def test_an_account_not_given_tritomoor_is_refused(app, signed_in):
    make(signed_in, programs=("pm",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert "/tritomoor/" not in text(sara.get("/"))
    assert sara.get("/tritomoor/").status_code in (302, 403)


def test_the_administrator_can_give_it(app, signed_in):
    assert 'value="tritomoor"' in text(signed_in.get("/admin/?tab=new"))
