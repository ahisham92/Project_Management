"""WSGI entry point.

Hosts such as PythonAnywhere, or servers like gunicorn and uWSGI, serve the
application themselves rather than running ``run.py``. They import this file and
look for a module-level ``application``.

Anything that needs configuring is read from the environment, so set those
variables before this module is imported — on PythonAnywhere that means the
``os.environ`` lines at the top of the WSGI file in the Web tab. See the README
under "PythonAnywhere" for the exact contents.
"""

from app import create_app

application = create_app()

# gunicorn and uWSGI look for "app" by convention; PythonAnywhere wants
# "application". Both names point at the same object.
app = application
