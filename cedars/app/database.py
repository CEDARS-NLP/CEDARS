"""Initialize database and object-storage connections (framework-agnostic).

Rewritten for the FastAPI migration. Replaces ``flask_pymongo`` / ``flask.g``
with a plain :class:`pymongo.MongoClient` whose ``mongo.db`` resolves to the
*current project's* database via a context variable, so the ~140
``mongo.db["COLLECTION"]`` call sites in :mod:`app.db` remain unchanged. S3 is
exposed as lazy boto3 singletons.
"""
import os
import contextvars
from urllib.parse import quote_plus

import boto3
from pymongo import MongoClient
from dotenv import load_dotenv
from loguru import logger
from botocore.exceptions import ClientError


load_dotenv()


def _build_mongo_uri():
    """Build the Mongo connection URI from environment (mirrors ``config.py``)."""
    protocol = os.getenv("DB_PROTOCOL", "mongodb")
    user = os.getenv("DB_USER")
    pwd = quote_plus(os.getenv("DB_PWD") or "")
    name = os.getenv("DB_NAME")
    params = os.getenv("DB_PARAMS", "")
    replica_set = os.getenv("DB_REPLICA_SET")
    if replica_set:
        return f"{protocol}://{user}:{pwd}@{replica_set}/{name}?{params}"
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    return f"{protocol}://{user}:{pwd}@{host}:{port}/{name}?{params}"


MONGO_URI = _build_mongo_uri()

# The metadata database holds *global* (non project-scoped) state:
#   - USERS    : global accounts used for authentication
#   - PROJECTS : registry of all projects (for listing / lookup)
META_DB_NAME = os.getenv("META_DB_NAME", "cedars_meta")

# Fallback database name used when no project context is bound (maintenance
# scripts, or the legacy single-project layout).
DEFAULT_DB_NAME = os.getenv("DB_NAME") or "cedars"

_client = None


def get_client():
    """Return a process-wide :class:`MongoClient` (created lazily)."""
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client


# --- project context -------------------------------------------------------

_current_project_db = contextvars.ContextVar("cedars_current_project_db", default=None)


def project_db_name(project_id):
    """Map a ``project_id`` to its dedicated Mongo database name."""
    return f"cedars_proj_{project_id}"


def set_current_project_db(db_name):
    """Bind the current context to ``db_name``; returns a reset token."""
    return _current_project_db.set(db_name)


def reset_current_project_db(token):
    """Undo a previous :func:`set_current_project_db` using its token."""
    _current_project_db.reset(token)


def get_current_project_db_name():
    """Return the database name bound to the current context (or the default)."""
    return _current_project_db.get() or DEFAULT_DB_NAME


class _MongoProxy:
    """Drop-in replacement for the old ``flask_pymongo.PyMongo`` handle.

    ``mongo.db`` resolves to the *current project's* database so that existing
    ``mongo.db["COLLECTION"]`` usage keeps working without edits.
    """

    @property
    def db(self):
        return get_client()[get_current_project_db_name()]

    @property
    def cx(self):
        return get_client()


mongo = _MongoProxy()


def get_meta_db():
    """Return the shared metadata database (global users + project registry)."""
    return get_client()[META_DB_NAME]


# --- object storage (S3 / MinIO) ------------------------------------------

def get_bucket_name():
    """Return the configured S3 bucket name, defaulting to cedars-{project_id}."""
    explicit = os.getenv("S3_BUCKET")
    if explicit:
        return explicit
    db_name = get_current_project_db_name()
    prefix = "cedars_proj_"
    project_id = db_name[len(prefix):] if db_name.startswith(prefix) else db_name
    return f"cedars-{project_id}"


def project_s3_prefix():
    """Return an S3 key prefix that isolates the current project's objects."""
    return get_current_project_db_name()


def _new_s3(resource=False):
    """Construct a boto3 S3 client or resource from environment credentials.

    Falls back to MINIO_ACCESS_KEY / MINIO_SECRET_KEY when the AWS_* vars are
    absent, and defaults the endpoint to http://minio:9000 in that case.
    """
    in_aws_mode = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    kwargs = {
        "region_name": os.getenv("REGION", "us-east-1"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("MINIO_ACCESS_KEY"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("MINIO_SECRET_KEY"),
    }
    # Use explicit endpoint when set; otherwise default to MinIO in self-hosted mode.
    endpoint = os.getenv("S3_ENDPOINT_URL") or (None if in_aws_mode else "http://minio:9000")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    factory = boto3.resource if resource else boto3.client
    return factory("s3", **kwargs)


def get_s3():
    """Return a boto3 S3 *client*, creating the bucket if it does not exist."""
    s3_client = _new_s3(resource=False)
    bucket_name = get_bucket_name()
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' already exists in object storage")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            logger.info(f"Bucket '{bucket_name}' not found — creating it")
            s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' created")
        else:
            logger.error(f"Error checking if bucket exists: {e}")
            raise
    return s3_client


def get_s3_resource():
    """Return a boto3 S3 *resource* (used for versioned delete operations)."""
    return _new_s3(resource=True)


class _LazyProxy:
    """Minimal lazy singleton proxy (replaces werkzeug ``LocalProxy``)."""

    def __init__(self, factory):
        self._factory = factory
        self._obj = None

    def _get(self):
        if self._obj is None:
            self._obj = self._factory()
        return self._obj

    def __getattr__(self, name):
        return getattr(self._get(), name)


# ``mongo`` (the project-scoped handle) is defined above. S3 handles are lazy so
# that importing this module never touches the network.
s3 = _LazyProxy(get_s3)
s3_resource = _LazyProxy(get_s3_resource)
