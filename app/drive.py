"""Putting one file on Google Drive, and putting it there again tomorrow.

Written against Drive's REST API with nothing but the standard library. The
alternative is Google's own client, which pulls in a dozen packages and a
cryptography build — a lot to install on a small shared host for one upload a
day.

That is affordable because of how it signs in. A **service account** would need
a JWT signed with RSA, which does need a crypto library; and its Drive is not
your Drive, so the file would land somewhere you cannot see without sharing it
back. A **refresh token** for your own account needs no signing at all — it is
one form post for an access token — and the file lands in your own Drive where
you can open it.

The same file every night, not a new one:

    look for a file with this name in this folder
      found     -> replace its contents  (PATCH .../files/{id}?uploadType=media)
      not found -> create it             (POST  .../files?uploadType=multipart)

Replacing keeps the file's id, so its link never changes and Drive keeps its
own version history — yesterday's copy is still there under "Manage versions"
without a second file cluttering the folder.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Mapping

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

# The narrowest scope that can do this: the app sees only the files it created
# itself, never the rest of your Drive.
SCOPE = "https://www.googleapis.com/auth/drive.file"

TIMEOUT = 120


class DriveError(Exception):
    """Anything Drive refused, in words worth showing on a screen."""


def configured(settings: Mapping[str, str]) -> bool:
    """Whether there is enough here to upload at all."""
    return all(settings.get(key) for key in ("client_id", "client_secret", "refresh_token"))


def settings_from_env(env: Mapping[str, str]) -> dict[str, str]:
    """Where the credentials live: the environment, never the database.

    A refresh token is a key to somebody's Drive. Keeping it out of the
    database keeps it out of the nightly backup, which would otherwise carry a
    copy of it to Drive.
    """
    return {
        "client_id": env.get("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": env.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "refresh_token": env.get("GOOGLE_REFRESH_TOKEN", "").strip(),
        "folder_id": env.get("GOOGLE_DRIVE_FOLDER_ID", "").strip(),
        "file_name": env.get("BACKUP_FILE_NAME", "").strip(),
    }


def _post_form(url: str, fields: Mapping[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return _send(request)


def _send(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            raw = answer.read()
    except urllib.error.HTTPError as exc:
        raise DriveError(_why(exc)) from exc
    except urllib.error.URLError as exc:
        raise DriveError(
            f"Could not reach Google ({exc.reason}). On a host that only allows "
            f"listed sites, oauth2.googleapis.com and www.googleapis.com have to "
            f"be among them."
        ) from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _why(exc: urllib.error.HTTPError) -> str:
    """Google's own reason, rather than a bare status code."""
    try:
        said = json.loads(exc.read().decode("utf-8"))
    except Exception:                                # noqa: BLE001 - the code is the fallback
        return f"Google said {exc.code}"

    if isinstance(said.get("error"), dict):
        detail = said["error"].get("message") or said["error"].get("status") or ""
        return f"Google said {exc.code}: {detail}" if detail else f"Google said {exc.code}"
    if said.get("error"):
        detail = said.get("error_description") or said["error"]
        if said["error"] == "invalid_grant":
            detail += (" — the refresh token is no longer good. Run"
                       " `python run.py drive-auth` again to get a new one.")
        return f"Google said {exc.code}: {detail}"
    return f"Google said {exc.code}"


def access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """An hour's worth of access, from the long-lived refresh token."""
    answer = _post_form(TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not token:
        raise DriveError("Google did not return an access token")
    return str(token)


def find(token: str, name: str, folder_id: str = "") -> str:
    """The id of the file already holding the backups, or "" for the first time.

    Only files this app created are visible to it, so nothing else of yours can
    be matched by name and overwritten.
    """
    terms = [f"name = '{name.replace(chr(39), chr(92) + chr(39))}'", "trashed = false"]
    if folder_id:
        terms.append(f"'{folder_id}' in parents")

    query = urllib.parse.urlencode({
        "q": " and ".join(terms),
        "fields": "files(id, name, modifiedTime, size)",
        "pageSize": "10",
        "spaces": "drive",
    })
    answer = _request(f"{FILES_URL}?{query}", token)
    files = answer.get("files") or []
    return str(files[0]["id"]) if files else ""


def _request(url: str, token: str, method: str = "GET", data: bytes | None = None,
             content_type: str = "") -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return _send(urllib.request.Request(url, data=data, method=method, headers=headers))


def create(token: str, name: str, data: bytes, folder_id: str = "") -> dict[str, Any]:
    """A new file, with its metadata and its contents in one request."""
    metadata: dict[str, Any] = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]

    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
        json.dumps(metadata).encode("utf-8"),
        f"\r\n--{boundary}\r\nContent-Type: application/zip\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    url = f"{UPLOAD_URL}?uploadType=multipart&fields=id,name,modifiedTime,size"
    return _request(url, token, "POST", body, f"multipart/related; boundary={boundary}")


def replace(token: str, file_id: str, data: bytes) -> dict[str, Any]:
    """The same file, holding today's backup instead of yesterday's.

    The id does not change, so the link you shared still works and Drive keeps
    the older contents under its own version history.
    """
    url = f"{UPLOAD_URL}/{file_id}?uploadType=media&fields=id,name,modifiedTime,size"
    return _request(url, token, "PATCH", data, "application/zip")


def upload(settings: Mapping[str, str], data: bytes, name: str = "") -> dict[str, Any]:
    """Put the backup on Drive, replacing the one that is there.

    Returns what Drive says about the file — its id, when it was written, and
    how big it is — so the app can show that the night's backup really landed.
    """
    if not configured(settings):
        raise DriveError(
            "Google Drive is not set up. Run `python run.py drive-auth` and put the "
            "three values it prints into the environment.")

    from .backup import DEFAULT_FILE_NAME

    filename = name or settings.get("file_name") or DEFAULT_FILE_NAME
    token = access_token(settings["client_id"], settings["client_secret"],
                         settings["refresh_token"])
    folder = settings.get("folder_id", "")

    existing = find(token, filename, folder)
    said = replace(token, existing, data) if existing else create(token, filename, data, folder)
    said["replaced"] = bool(existing)
    said["link"] = f"https://drive.google.com/file/d/{said.get('id', '')}/view"
    return said


# --- getting a refresh token in the first place ----------------------------

def consent_url(client_id: str, redirect_uri: str) -> str:
    """Where to send a browser to say yes, once."""
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        # Without both of these Google hands back an access token and no
        # refresh token, and the whole thing works today and not tomorrow.
        "access_type": "offline",
        "prompt": "consent",
    })


def exchange(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, Any]:
    """The one-time code from that browser, traded for a refresh token."""
    answer = _post_form(TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if not answer.get("refresh_token"):
        raise DriveError(
            "Google returned no refresh token. That happens when the account has "
            "already granted this app access — remove it under "
            "myaccount.google.com/permissions and try again.")
    return answer
