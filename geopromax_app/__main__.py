"""Run GeoProMax alone for development: ``GEOPROMAX_DEV_ACCOUNT=me python -m geopromax_app``."""

import os

from .app import create_app

if __name__ == "__main__":
    os.environ.setdefault("GEOPROMAX_DEV_ACCOUNT", "me")
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5062")), debug=True)
