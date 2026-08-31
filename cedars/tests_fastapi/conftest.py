"""Test configuration for the FastAPI backend.

Uses file-backed SQLite databases (one per test, in a throwaway temp dir)
instead of a live PostgreSQL server: `_build_pg_uri` is patched to emit sqlite
URLs, so `cedars.app.database` engine providers transparently create SQLite
engines. SQLite is a fully supported dialect in the SQL layer (see
`db_inserts._upsert_ignore`'s dialect-aware ON CONFLICT branch), so this
exercises the same code paths a real Postgres deployment would use.
"""
import os
import shutil
import tempfile

import pytest

# Environment must be set before importing the app modules.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DB_PROTOCOL", "sqlite")
os.environ.setdefault("DB_HOST", "")
os.environ.setdefault("DB_PORT", "")
os.environ.setdefault("DB_USER", "")
os.environ.setdefault("DB_PWD", "")
os.environ.setdefault("DB_PARAMS", "")
os.environ.setdefault("GLOBAL_DB_NAME", "cedars_global")
os.environ.setdefault("REDIS_PROTOCOL", "redis")
os.environ.setdefault("REDIS_URL", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("AUTH_TOKEN", "")
os.environ.setdefault("S3_BUCKET", "cedars-test")

# Back the RQ queues with fakeredis. Patch ``Redis.from_url`` *before* importing
# any app module that builds a queue (``app.queues`` runs at import time).
import fakeredis  # noqa: E402
import redis  # noqa: E402

_fake_redis = fakeredis.FakeStrictRedis()
redis.Redis.from_url = staticmethod(lambda *a, **k: _fake_redis)

from app import database  # noqa: E402  (import after env setup)
from app.database import init_db  # noqa: E402
from app.database.global_app_tables import GlobalBase  # noqa: E402

# Silence the verbose per-call DEBUG logging during tests.
from loguru import logger as _loguru_logger  # noqa: E402

import app as _app_pkg  # noqa: E402

_app_pkg.setup_logging = lambda: None  # avoid re-adding stdout handlers per test
_loguru_logger.remove()


@pytest.fixture(autouse=True)
def patch_database(monkeypatch):
    """Route all SQL access through fresh, per-test SQLite databases."""
    tmp_dir = tempfile.mkdtemp(prefix="cedars_test_")

    monkeypatch.setattr(database, "_build_pg_uri", lambda db_name: f"sqlite:///{tmp_dir}/{db_name}.db")
    # Reset the cached engine singletons so they're rebuilt against tmp_dir.
    monkeypatch.setattr(database, "_global_engine", None)
    monkeypatch.setattr(database, "_admin_engine", None)
    monkeypatch.setattr(database, "_project_engines", {})
    # SQLite has no CREATE/DROP DATABASE - a project "database" is just a new
    # engine/file, created lazily by get_project_engine on first use.
    monkeypatch.setattr(init_db, "create_project_database", lambda project_id: None)
    monkeypatch.setattr(init_db, "drop_project_database",
                        lambda project_id: database.dispose_project_engine(project_id))

    GlobalBase.metadata.create_all(database.get_global_engine())

    _fake_redis.flushall()
    yield
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client():
    """A FastAPI TestClient with cookie persistence."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

