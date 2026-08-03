"""Test configuration for the FastAPI backend.

Patches the Mongo client with an in-memory ``mongomock`` instance so the API can
be exercised without a running MongoDB. Redis/RQ are not touched by the P1 tests.
"""
import os

import mongomock
import pytest

# Environment must be set before importing the app modules.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DB_NAME", "cedars")
os.environ.setdefault("META_DB_NAME", "cedars_meta")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PWD", "test")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "27017")
os.environ.setdefault("DB_PARAMS", "")
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

# mongomock 4.3.0 predates pymongo 4.10's bulk-update ``sort`` parameter, which
# pymongo 4.12 always forwards. Strip it so bulk_write works under the test double.
import mongomock.collection as _mmc  # noqa: E402

_orig_add_update = _mmc.BulkOperationBuilder.add_update


def _add_update_compat(self, selector, doc, *args, **kwargs):
    kwargs.pop("sort", None)
    return _orig_add_update(self, selector, doc, *args, **kwargs)


_mmc.BulkOperationBuilder.add_update = _add_update_compat

# Silence the verbose per-call DEBUG logging during tests.
from loguru import logger as _loguru_logger  # noqa: E402

import app as _app_pkg  # noqa: E402

_app_pkg.setup_logging = lambda: None  # avoid re-adding stdout handlers per test
_loguru_logger.remove()

_mock_client = mongomock.MongoClient()


@pytest.fixture(autouse=True)
def patch_mongo(monkeypatch):
    """Route all Mongo access through a shared in-memory client, reset per test."""
    from app import db  # noqa: PLC0415
    for name in _mock_client.list_database_names():
        _mock_client.drop_database(name)
    _fake_redis.flushall()
    monkeypatch.setattr(database, "_client", _mock_client, raising=False)
    monkeypatch.setattr(database, "get_client", lambda: _mock_client)
    # PINES prediction queries use the $reduce aggregation operator, which
    # mongomock does not implement. Tests carry no PINES data, so stub them out.
    monkeypatch.setattr(db, "get_formatted_patient_predictions", lambda *a, **k: [])
    monkeypatch.setattr(db, "get_max_prediction_score", lambda *a, **k: None)
    yield


@pytest.fixture()
def client():
    """A FastAPI TestClient with cookie persistence."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
