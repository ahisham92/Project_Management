"""WSGI entry point.

Hosts such as PythonAnywhere, or servers like gunicorn and uWSGI, serve the
application themselves rather than running ``run.py``. They import this file and
look for a module-level ``application``.

Project control answers at the root. Two applications of their own are mounted
beside it when they are installed: the older comment sheet in front of
``/crs/classic``, and Triton, the quay element designer, in front of
``/triton``, behind project control's sign-in. They are joined at the WSGI layer
rather than inside Flask, so none has to know how the others work and one web
app on the host serves them all.

Anything that needs configuring is read from the environment, so set those
variables before this module is imported — on PythonAnywhere that means the
``os.environ`` lines at the top of the WSGI file in the Web tab. See the README
under "PythonAnywhere" for the exact contents.
"""

from werkzeug.middleware.dispatcher import DispatcherMiddleware

from app import create_app
from app.crs import MOUNT, load as load_crs
from app.triton_door import mounts as triton_mounts

control = create_app()

# Nothing installed leaves the root application to answer those addresses
# itself, with a page saying what to do about it. That is better than a 404 on a
# door the front page offers, and it means this file is the same before and after.
crs = load_crs()
mounted = {MOUNT: crs} if crs else {}
mounted.update(triton_mounts(control))
application = DispatcherMiddleware(control, mounted) if mounted else control

# gunicorn and uWSGI look for "app" by convention; PythonAnywhere wants
# "application". Both names point at the same object.
app = application
