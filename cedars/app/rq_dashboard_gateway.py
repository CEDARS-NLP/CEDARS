"""Per-project stock rq-dashboard, embedded as a WSGI sub-application.

Builds and caches one Flask + ``rq-dashboard`` app per project, each pointed at
that project's ACL-scoped Redis connection (see :mod:`app.queues`). This module
has no auth of its own - access control lives entirely in
:mod:`app.routers.rq_dashboard`, which runs ``require_project_admin`` before any
request reaches the cached app returned here.
"""
from threading import Lock

import rq_dashboard
from a2wsgi import WSGIMiddleware
from flask import Flask

from .queues import get_project_redis_url

API_PREFIX = "/api/v1"

_apps: dict = {}
_lock = Lock()


def _build_flask_app(project_id: str) -> Flask:
    app = Flask(__name__)
    app.config.from_object(rq_dashboard.default_settings)
    # No RQ_DASHBOARD_USERNAME/PASSWORD - the FastAPI route in front of this
    # app is the only auth layer (see routers/rq_dashboard.py).
    app.config["RQ_DASHBOARD_REDIS_URL"] = get_project_redis_url(project_id)
    rq_dashboard.web.setup_rq_connection(app)
    app.register_blueprint(rq_dashboard.blueprint,
                           url_prefix=f"{API_PREFIX}/projects/{project_id}/rq")
    return app


def get_dashboard_asgi_app(project_id: str):
    """Return a cached ASGI-wrapped rq-dashboard app scoped to ``project_id``."""
    if project_id not in _apps:
        with _lock:
            if project_id not in _apps:
                _apps[project_id] = WSGIMiddleware(_build_flask_app(project_id))
    return _apps[project_id]


def forget_dashboard_app(project_id: str) -> None:
    """Drop a cached dashboard app (e.g. after project termination)."""
    with _lock:
        _apps.pop(project_id, None)
