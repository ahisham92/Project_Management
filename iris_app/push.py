"""Phone notifications (Web Push).

A notification never carries what a tool said, only who is asking: "Sketch
ProMax has a question". The phone opens Iris and decrypts the message there.

The site signs its pushes with a VAPID key pair made on first use and kept in
the data directory. Sending needs outbound internet, which PythonAnywhere's paid
plans have. Without ``pywebpush`` installed, or with no network, Iris still
works; the phone just does not buzz.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from .store import Store, data_folder

log = logging.getLogger("iris.push")

#: Why the last push failed ("" when it went), for the phone's notification test.
last_error = ""


def contact(site_url: str = "") -> str:
    """Who the push services may contact about this sender (VAPID "sub").

    Apple's push service refuses a token whose contact is a localhost address
    (403 BadJwtToken), which is why no iPhone got a notification at first: the
    site's own https address is used, or IRIS_PUSH_CONTACT when it is set.
    """
    import os

    chosen = os.environ.get("IRIS_PUSH_CONTACT", "").strip()
    if chosen:
        return chosen
    if site_url.startswith("https://") and "localhost" not in site_url:
        return site_url.rstrip("/")
    return "mailto:iris@example.com"


def _key_file() -> Path:
    return data_folder() / "vapid.pem"


def _vapid():
    """The site's VAPID key, made the first time it is needed. None without pywebpush."""
    try:
        from py_vapid import Vapid
    except ImportError:
        return None
    path = _key_file()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Vapid()
        key.generate_keys()
        key.save_key(str(path))
    return Vapid.from_file(str(path))


def public_key() -> str:
    """The application server key the phone subscribes with, or "" when push is off."""
    vapid = _vapid()
    if vapid is None:
        return ""
    from cryptography.hazmat.primitives import serialization

    raw = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def notify(store: Store, account: str, payload: dict[str, Any], contact: str = "") -> int:
    """Tell every phone on the account. Returns how many took it; never raises."""
    global last_error
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        last_error = "The site can't send notifications: pywebpush isn't installed (pip install -r requirements.txt)."
        return 0
    try:
        vapid = _vapid()
    except Exception:                                   # noqa: BLE001 - a folder it cannot write
        log.exception("Iris could not load its push key")
        return 0
    sent = 0
    for phone in store.phones(account):
        try:
            webpush(
                subscription_info={"endpoint": phone["endpoint"],
                                   "keys": {"p256dh": phone["p256dh"], "auth": phone["auth"]}},
                data=json.dumps(payload),
                vapid_private_key=vapid,
                vapid_claims={"sub": contact or globals()["contact"]()},
                ttl=6 * 3600,
                timeout=5,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", 0)
            if status in (404, 410):
                store.remove_phone(phone["endpoint"])   # the phone unsubscribed or was reset
            else:
                last_error = f"The phone's push service said {status or 'no'}: {getattr(exc.response, 'text', '') or exc}"[:300]
                log.warning("Iris push failed: %s", exc)
        except Exception as exc:                        # noqa: BLE001 - no network, say and carry on
            last_error = f"Couldn't reach the push service: {exc}"[:300]
            log.warning("Iris push failed: %s", exc)
    return sent
