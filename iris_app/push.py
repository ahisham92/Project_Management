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

#: Who the push services may contact about this sender. Any mailto or https URL.
CONTACT = "mailto:iris@localhost"


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


def notify(store: Store, account: str, payload: dict[str, Any]) -> int:
    """Tell every phone on the account. Returns how many took it; never raises."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
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
                vapid_claims={"sub": CONTACT},
                ttl=6 * 3600,
                timeout=5,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", 0)
            if status in (404, 410):
                store.remove_phone(phone["endpoint"])   # the phone unsubscribed or was reset
            else:
                log.warning("Iris push failed: %s", exc)
        except Exception as exc:                        # noqa: BLE001 - no network, say and carry on
            log.warning("Iris push failed: %s", exc)
    return sent
