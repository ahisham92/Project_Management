# Iris

**The line between any AI tool and the person it works for.**

A tool working on its own for hours (an autopilot in a Revit add-in, a long
report, a model check) sometimes needs a person: a question only they can
answer, a progress note, a Stop button. Iris carries those to the person's
phone and brings the answer back.

- **One account, many tools.** Each person signs in once on their phone. Every
  tool they connect shows up as its own tab, with its own notifications and its
  own Disconnect.
- **Connecting a tool is one scan.** The tool shows a QR code in its settings;
  the phone scans it and confirms. No keys or addresses to type.
- **One-tap answers.** A question can carry answer buttons, a free-text box, and
  what the tool will assume if nobody answers in time.
- **Nothing readable on the server.** Every message is encrypted on the PC and
  decrypted on the phone with a key that travels inside the QR code, after the
  `#`, so it never reaches the server. Notifications say only who is asking.
- **Tools only call out.** A PC behind a company proxy needs nothing opened:
  the tool sends over HTTPS and checks back for answers.

## How it is put together

| Part | What it is |
|---|---|
| `iris_app/` | The server: a small Flask app with one SQLite file, and the phone app (plain HTML and JavaScript, installable to the home screen, with Web Push). |
| `iris_app/clients/python/iris_client.py` | A tool's side, in Python. |
| `iris_app/clients/csharp/IrisClient.cs` | A tool's side, in C# (.NET Framework 4.8 and .NET 8+). |
| `iris_app/static/iris-crypto.js` | The message format in JavaScript, used by the phone and by any JavaScript tool. |
| `iris_app/API.md` | The web API, for a tool in any other language. |

## Running it inside a site

Iris has no sign-in of its own. It is meant to be mounted inside a site that
already signs people in, at an address such as `/iris`:

```python
from iris_app.wsgi import SITE_KEY, application as iris, is_public

def mounted(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if not is_public(path):
        user = who_is_signed_in(environ)          # the site's own session
        if user is None:
            ...                                   # send them to the site's login
        environ[SITE_KEY] = {"id": user.id, "name": user.name}
    return iris(environ, start_response)
```

`is_public` lets through the tool API (tools carry their own token), the
pairing landing page and the files the home-screen app needs. Everything else
answers only the account the site names.

Set `IRIS_DATA_DIR` to a folder outside the code: the database and the push
key live there. `IRIS_KEEP_DAYS` (30 unless set) is how long messages are kept.

**Phone notifications** need outbound internet from the server (on
PythonAnywhere, any paid plan) and `pywebpush`. Without either, Iris still
works; phones just do not buzz. On iPhone, notifications work after
**Share > Add to Home Screen** (iOS 16.4 or later).

## Trying it alone

```bash
python -m iris_app            # http://127.0.0.1:5077, everyone is one "dev" account
pytest tests/test_iris_app.py tests/test_iris_door.py
```

## Connecting a tool

```python
from iris_client import Iris

iris = Iris.load("my-tool.json", site="https://example.pythonanywhere.com/iris")
if not iris.connected:
    print(iris.start_pairing("My tool", commands=["Pause", "Resume", "Stop"]))  # show as a QR code
    iris.wait_for_phone()
qid = iris.ask("4 lengths or 3?", options=["4", "3"], assumed="4")
for m in iris.inbox():
    print(m["kind"], m["value"])      # answer / command / message, decrypted
```

The C# client has the same calls. See `API.md` for the rest.
