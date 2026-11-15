"""Run JEDSA alone for development: ``python -m jedsa_app``, then open http://127.0.0.1:5058/."""

import os

from .app import create_app

if __name__ == "__main__":
    os.environ.setdefault("JEDSA_DEV_ACCOUNT", "me")
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5058")), debug=True)
