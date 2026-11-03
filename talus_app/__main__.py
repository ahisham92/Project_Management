"""Run Talus alone for development: ``TALUS_DEV_ACCOUNT=me python -m talus_app``."""

import os

from .app import create_app

if __name__ == "__main__":
    os.environ.setdefault("TALUS_DEV_ACCOUNT", "me")
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5057")), debug=True)
