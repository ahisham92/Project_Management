"""TritoMoor, the static mooring analysis program, served at /tritomoor/."""

from __future__ import annotations


def text(response) -> str:
    return response.get_data(as_text=True)


def make(signed_in, programs):
    return signed_in.post("/admin/users", data={
        "username": "sara", "password": "longenough1", "name": "Sara", "programs": list(programs)})


def test_the_front_page_has_a_door_to_it(signed_in):
    page = text(signed_in.get("/"))
    assert "Open TritoMoor" in page
    assert 'href="/tritomoor/"' in page


def test_it_serves_the_program(signed_in):
    answer = signed_in.get("/tritomoor/")
    assert answer.status_code == 200
    assert answer.mimetype == "text/html"
    assert "TritoMoor" in text(answer)


def test_the_bare_address_goes_to_it(signed_in):
    answer = signed_in.get("/tritomoor")
    assert answer.status_code in (301, 302, 308)
    assert answer.headers["Location"].endswith("/tritomoor/")


def test_a_stranger_is_sent_to_sign_in(client):
    answer = client.get("/tritomoor/")
    assert answer.status_code == 302
    assert "/login" in answer.headers["Location"]


def test_an_account_without_it_is_refused(app, signed_in):
    make(signed_in, programs=("pm",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert sara.get("/tritomoor/").status_code == 403
    assert "Open TritoMoor" not in text(sara.get("/"))


def test_an_account_given_it_gets_it(app, signed_in):
    make(signed_in, programs=("tritomoor",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert sara.get("/tritomoor/").status_code == 200
    assert "Open TritoMoor" in text(sara.get("/"))
