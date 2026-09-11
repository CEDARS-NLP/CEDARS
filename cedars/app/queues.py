"""Redis / RQ queue handles (framework-agnostic).

Each project has its own task/ops queues, served over its own Redis ACL user
(see :mod:`app.database.redis_acl`) so one project's dashboard/connection
cannot see another project's queues or jobs. Enqueued jobs are always given an
explicit, queue-name-prefixed ``job_id`` (see :class:`ProjectQueue`) so a
project's job hashes are also covered by its ACL key patterns.
"""
import os
import re
from threading import Lock
from uuid import uuid4

from redis import Redis
from rq import Queue

TASK_QUEUE_PREFIX = "task"
OPS_QUEUE_PREFIX = "ops"
JOB_TIMEOUT = 3600
OPERATION_TIMEOUT = 86400

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_project_id(project_id: str) -> str:
    """Reject project ids that can't safely be embedded in Redis key/ACL names."""
    if not project_id or not _PROJECT_ID_RE.match(project_id):
        raise ValueError(f"Invalid project_id for Redis queue naming: {project_id!r}")
    return project_id


def task_queue_name(project_id: str) -> str:
    """Name of ``project_id``'s NLP task queue."""
    return f"{TASK_QUEUE_PREFIX}-{_validate_project_id(project_id)}"


def ops_queue_name(project_id: str) -> str:
    """Name of ``project_id``'s operations queue."""
    return f"{OPS_QUEUE_PREFIX}-{_validate_project_id(project_id)}"


class ProjectQueue(Queue):
    """An RQ ``Queue`` that always assigns a queue-name-prefixed ``job_id``.

    RQ auto-generates a bare UUID job_id when one isn't supplied, which would
    not be covered by this project's Redis ACL key patterns (``~rq:*{queue}*``).
    Prefixing every job_id with the queue name keeps job hashes inside the
    project's own ACL-scoped keyspace. RQ's job_id validation only allows
    letters, numbers, underscores and dashes (no colons), so the prefix is
    joined with a dash.
    """

    def enqueue_call(self, *args, **kwargs):  # noqa: D102 - see class docstring
        if not kwargs.get("job_id"):
            kwargs["job_id"] = f"{self.name}-{uuid4().hex}"
        return super().enqueue_call(*args, **kwargs)


def _redis_host_port():
    return os.getenv("REDIS_URL"), os.getenv("REDIS_PORT")


def get_admin_redis() -> Redis:
    """Connection used only to administer Redis ACL users (the default user)."""
    protocol = os.getenv("REDIS_PROTOCOL", "redis")
    token = os.getenv("AUTH_TOKEN", "")
    host, port = _redis_host_port()
    return Redis.from_url(f"{protocol}://:{token}@{host}:{port}/0")


def get_project_redis_url(project_id: str) -> str:
    """Build the ACL-scoped Redis URL for ``project_id`` (used by rq-dashboard)."""
    from .database import get_global_engine
    from .database.redis_acl import get_project_redis_credentials

    username, secret = get_project_redis_credentials(get_global_engine(), project_id)
    protocol = os.getenv("REDIS_PROTOCOL", "redis")
    host, port = _redis_host_port()
    return f"{protocol}://{username}:{secret}@{host}:{port}/0"


_project_redis_cache: dict = {}
_cache_lock = Lock()


def get_project_redis(project_id: str) -> Redis:
    """Return a cached Redis connection authenticated as ``project_id``'s ACL user."""
    if project_id not in _project_redis_cache:
        with _cache_lock:
            if project_id not in _project_redis_cache:
                url = get_project_redis_url(project_id)
                _project_redis_cache[project_id] = Redis.from_url(url)
    return _project_redis_cache[project_id]


def forget_project_redis(project_id: str) -> None:
    """Drop and close a project's cached Redis connection (e.g. after termination)."""
    with _cache_lock:
        conn = _project_redis_cache.pop(project_id, None)
    if conn is not None:
        conn.close()


def get_task_queue(project_id: str) -> ProjectQueue:
    """Return ``project_id``'s NLP task queue."""
    return ProjectQueue(task_queue_name(project_id), connection=get_project_redis(project_id),
                        default_timeout=JOB_TIMEOUT)


def get_ops_queue(project_id: str) -> ProjectQueue:
    """Return ``project_id``'s operations queue."""
    return ProjectQueue(ops_queue_name(project_id), connection=get_project_redis(project_id),
                        default_timeout=OPERATION_TIMEOUT)
