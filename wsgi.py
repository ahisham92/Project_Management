"""WSGI entry point.

Hosts such as PythonAnywhere, or servers like gunicorn and uWSGI, serve the
application themselves rather than running ``run.py``. They import this file and
look for a module-level ``application``.

Two applications are served from here. Project control answers at the root, and
the comment response sheet — when one is installed — is mounted in front of
``/crs`` as an application of its own, with its own routes, templates and data.
They are joined at the WSGI layer rather than inside Flask, so neither has to
know anything about the other and one web app on the host serves the pair.

Anything that needs configuring is read from the environment, so set those
variables before this module is imported — on PythonAnywhere that means the
``os.environ`` lines at the top of the WSGI file in the Web tab. See the README
under "PythonAnywhere" for the exact contents.
"""

from werkzeug.middleware.dispatcher import DispatcherMiddleware

from app import create_app
from app.crs import MOUNT, load as load_crs

control = create_app()

# No CRS installed leaves the root application to answer /crs itself, with a
# page saying what to do about it. That is better than a 404 on a door the
# front page offers, and it means this file is the same before and after.
crs = load_crs()
application = DispatcherMiddleware(control, {MOUNT: crs}) if crs else control

# gunicorn and uWSGI look for "app" by convention; PythonAnywhere wants
# "application". Both names point at the same object.
app = application
