"""Run Pontoon alone for development: ``PONTOON_DEV_ACCOUNT=me python -m pontoon_app``."""

import os

from .app import create_app

if __name__ == "__main__":
    os.environ.setdefault("PONTOON_DEV_ACCOUNT", "me")
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5058")), debug=True)
