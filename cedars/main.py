"""Top-level ASGI entrypoint shim.

Allows serving the app as ``main:app`` (from the ``cedars/`` directory) while the
real application factory lives in :mod:`app.main` (served as ``app.main:app``).
"""
from app.main import app

__all__ = ["app"]
