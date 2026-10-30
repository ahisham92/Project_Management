"""Run Iris alone on this computer, for trying it out: python -m iris_app

Everybody who opens it is the same account (IRIS_DEV_ACCOUNT, "dev" unless set).
Phones need HTTPS for encryption and notifications, so use it on the PC itself.
"""

import os

os.environ.setdefault("IRIS_DEV_ACCOUNT", "dev")

from .wsgi import get_app  # noqa: E402

get_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5077")))
