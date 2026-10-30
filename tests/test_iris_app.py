"""Iris end to end: a tool pairs, asks, the phone answers, the tool reads it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "iris_app" / "clients" / "python"))

from iris_app.app import SITE_KEY, create_app, is_public  # noqa: E402
from iris_app.store import Store  # noqa: E402
import iris_client  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IRIS_DEV_ACCOUNT", raising=False)
    clock = Clock()
    app = create_app(Store(tmp_path / "iris.db", clock=clock))
    pushes = []
    app.notify = lambda account, payload: pushes.append((account, payload)) or 1
    return app, clock, pushes


def phone(app, account="7", name="Ahmed"):
    client = app.test_client()
    client.environ_base[SITE_KEY] = {"id": account, "name": name}
    return client


def pair(app, name="Sketch ProMax", commands=("Stop", "Resume"), account="7"):
    tool = app.test_client()
    started = tool.post("/api/tool/pair", json={"name": name, "machine": "PC-01", "commands": list(commands)}).get_json()
    assert tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": started["secret"]}).get_json() == {"status": "waiting"}
    accepted = phone(app, account).post("/api/me/pair", json={"code": started["code"]}).get_json()
    done = tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": started["secret"]}).get_json()
    assert done["status"] == "connected" and done["tool_id"] == accepted["id"]
    return tool, {"Authorization": "Bearer " + done["token"]}, accepted


def test_public_paths():
    assert is_public("/pair") and is_public("/api/tool/messages") and is_public("/static/app.js")
    assert not is_public("/") and not is_public("/api/me/tools")


def test_pages_need_the_site_sign_in(world):
    app, _, _ = world
    assert app.test_client().get("/api/me/tools").status_code == 401
    assert app.test_client().get("/pair").status_code == 200
    assert phone(app).get("/").status_code == 200
    assert app.test_client().get("/manifest.webmanifest").get_json()["name"] == "Iris"


def test_pair_ask_answer_round_trip(world):
    app, _, pushes = world
    tool, auth, accepted = pair(app)
    assert accepted["commands"] == ["Stop", "Resume"]

    q = tool.post("/api/tool/messages", headers=auth, json={"kind": "question", "body": "v1.sealed-q"}).get_json()
    assert pushes == [("7", {"title": "Sketch ProMax", "body": "Sketch ProMax has a question", "tool": accepted["id"], "message": q["id"]})]

    me = phone(app)
    tools = me.get("/api/me/tools").get_json()["tools"]
    assert tools[0]["waiting"] == 1
    feed = me.get(f"/api/me/tools/{accepted['id']}/messages").get_json()["messages"]
    assert [m["body"] for m in feed] == ["v1.sealed-q"] and feed[0]["state"] == "open"

    me.post(f"/api/me/tools/{accepted['id']}/messages", json={"kind": "answer", "reply_to": q["id"], "body": "v1.sealed-a"})
    again = me.post(f"/api/me/tools/{accepted['id']}/messages", json={"kind": "answer", "reply_to": q["id"], "body": "v1.x"})
    assert again.status_code == 409

    inbox = tool.get("/api/tool/inbox?after=0", headers=auth).get_json()["messages"]
    assert [(m["kind"], m["reply_to"], m["body"]) for m in inbox] == [("answer", q["id"], "v1.sealed-a")]
    assert tool.get(f"/api/tool/inbox?after={inbox[-1]['id']}", headers=auth).get_json()["messages"] == []
    assert me.get("/api/me/tools").get_json()["tools"][0]["waiting"] == 0


def test_updates_notify_only_when_asked(world):
    app, _, pushes = world
    tool, auth, accepted = pair(app)
    tool.post("/api/tool/messages", headers=auth, json={"kind": "update", "body": "v1.u"})
    assert pushes == []
    phone(app).post(f"/api/me/tools/{accepted['id']}/notify", json={"notify": "all"})
    tool.post("/api/tool/messages", headers=auth, json={"kind": "update", "body": "v1.u"})
    assert pushes[-1][1]["body"] == "Sketch ProMax sent an update"


def test_tool_closes_a_question_it_assumed(world):
    app, _, _ = world
    tool, auth, accepted = pair(app)
    q = tool.post("/api/tool/messages", headers=auth, json={"kind": "question", "body": "v1.q"}).get_json()
    tool.post("/api/tool/messages", headers=auth, json={"kind": "closed", "reply_to": q["id"], "body": "v1.c"})
    late = phone(app).post(f"/api/me/tools/{accepted['id']}/messages", json={"kind": "answer", "reply_to": q["id"], "body": "v1.a"})
    assert late.status_code == 409
    again = tool.post("/api/tool/messages", headers=auth, json={"kind": "closed", "reply_to": q["id"], "body": "v1.c"})
    assert again.status_code == 409


def test_sides_cannot_send_each_others_kinds(world):
    app, _, _ = world
    tool, auth, accepted = pair(app)
    assert tool.post("/api/tool/messages", headers=auth, json={"kind": "command", "body": "v1.x"}).status_code == 400
    assert phone(app).post(f"/api/me/tools/{accepted['id']}/messages", json={"kind": "question", "body": "v1.x"}).status_code == 400


def test_accounts_see_only_their_own_tools(world):
    app, _, _ = world
    _, _, accepted = pair(app, account="7")
    other = phone(app, account="8")
    assert other.get("/api/me/tools").get_json()["tools"] == []
    assert other.get(f"/api/me/tools/{accepted['id']}/messages").status_code == 404
    assert other.delete(f"/api/me/tools/{accepted['id']}").status_code == 404


def test_disconnect_from_phone_cuts_the_tool_off(world):
    app, _, _ = world
    tool, auth, accepted = pair(app)
    assert phone(app).delete(f"/api/me/tools/{accepted['id']}").status_code == 200
    assert tool.get("/api/tool/inbox", headers=auth).status_code == 401
    assert phone(app).get("/api/me/tools").get_json()["tools"] == []


def test_codes_expire_and_work_once(world):
    app, clock, _ = world
    tool = app.test_client()
    started = tool.post("/api/tool/pair", json={"name": "X"}).get_json()
    clock.now += 11 * 60
    assert phone(app).post("/api/me/pair", json={"code": started["code"]}).status_code == 404
    status = tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": started["secret"]}).get_json()
    assert status["status"] == "expired"

    started = tool.post("/api/tool/pair", json={"name": "X"}).get_json()
    assert phone(app).post("/api/me/pair", json={"code": started["code"].lower()}).status_code == 200
    assert phone(app).post("/api/me/pair", json={"code": started["code"]}).status_code == 409
    assert tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": "wrong"}).status_code == 404


def test_token_is_handed_over_once(world):
    app, _, _ = world
    tool = app.test_client()
    started = tool.post("/api/tool/pair", json={"name": "X"}).get_json()
    phone(app).post("/api/me/pair", json={"code": started["code"]})
    first = tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": started["secret"]})
    assert first.get_json()["status"] == "connected"
    assert tool.get(f"/api/tool/pair/{started['pair_id']}", headers={"X-Pair-Secret": started["secret"]}).status_code == 404


def test_old_messages_are_dropped(world, monkeypatch):
    app, clock, _ = world
    monkeypatch.setenv("IRIS_KEEP_DAYS", "30")
    tool, auth, accepted = pair(app)
    tool.post("/api/tool/messages", headers=auth, json={"kind": "update", "body": "v1.old"})
    clock.now += 31 * 86400
    tool.post("/api/tool/messages", headers=auth, json={"kind": "update", "body": "v1.new"})
    feed = phone(app).get(f"/api/me/tools/{accepted['id']}/messages").get_json()["messages"]
    assert [m["body"] for m in feed] == ["v1.new"]


def test_python_client_encryption_round_trip():
    key = bytes(range(64))
    sealed = iris_client.seal(key, {"text": "PVC pipes: 4 lengths or 3?", "options": ["4", "3"]})
    assert sealed.startswith("v1.") and "PVC" not in sealed
    assert iris_client.open_sealed(key, sealed)["options"] == ["4", "3"]
    tampered = sealed[:-5] + ("A" if sealed[-5] != "A" else "B") + sealed[-4:]
    with pytest.raises(ValueError):
        iris_client.open_sealed(key, tampered)


def test_python_client_against_the_app(world, tmp_path):
    """The Python client end to end, talking to the app through its test client."""
    app, _, _ = world
    http = app.test_client()

    class Reply:
        def __init__(self, r):
            self.r = r

        def read(self):
            return self.r.data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        r = http.open(req.full_url.replace("https://site", ""), method=req.get_method(),
                      data=req.data, headers=dict(req.header_items()))
        if r.status_code >= 400:
            import io
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, r.status_code, "", {}, io.BytesIO(r.data))
        return Reply(r)

    iris_client.urllib.request.urlopen = urlopen
    iris = iris_client.Iris.load(tmp_path / "tool.json", site="https://site")
    link = iris.start_pairing("Sketch ProMax", machine="PC-01", commands=["Stop"])
    assert link.startswith("https://site/pair?c=") and "#k=" in link
    code = link.split("c=")[1].split("#")[0]
    key = iris_client._unb64u(link.split("#k=")[1])
    accepted = phone(app).post("/api/me/pair", json={"code": code}).get_json()
    assert iris.check_pairing() == "connected" and iris.connected

    qid = iris.ask("4 lengths or 3?", options=["4", "3"], assumed="4")
    sealed = phone(app).get(f"/api/me/tools/{accepted['id']}/messages").get_json()["messages"][0]["body"]
    assert iris_client.open_sealed(key, sealed)["text"] == "4 lengths or 3?"
    phone(app).post(f"/api/me/tools/{accepted['id']}/messages",
                    json={"kind": "answer", "reply_to": qid, "body": iris_client.seal(key, {"text": "3"})})
    got = iris.inbox()
    assert [(m["kind"], m["reply_to"], m["value"]) for m in got] == [("answer", qid, {"text": "3"})]
    assert iris.inbox() == []
    assert json.loads((tmp_path / "tool.json").read_text())["after"] == got[0]["id"]


def test_javascript_and_python_read_each_other(tmp_path):
    """The phone's WebCrypto code and the PC clients write the same format."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    key = bytes(range(64))
    from_python = iris_client.seal(key, {"text": "from python"})
    script = tmp_path / "check.js"
    script.write_text(
        "const C = require(%s);\n"
        "(async () => { const k = await C.importKey(%s);\n"
        "  const got = await C.open(k, %s);\n"
        "  const back = await C.seal(k, {text: 'from js', echo: got.text});\n"
        "  process.stdout.write(back); })();\n"
        % (json.dumps(str(ROOT / "iris_app" / "static" / "iris-crypto.js")),
           json.dumps(iris_client._b64u(key)), json.dumps(from_python)))
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30, check=True).stdout
    assert iris_client.open_sealed(key, out) == {"text": "from js", "echo": "from python"}


def test_push_key_is_made_once(tmp_path, monkeypatch):
    pytest.importorskip("py_vapid")
    from iris_app import push

    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path))
    first = push.public_key()
    assert len(iris_client._unb64u(first)) == 65 and push.public_key() == first
