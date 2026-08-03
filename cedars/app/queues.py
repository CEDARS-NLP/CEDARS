"""Redis / RQ queue handles (framework-agnostic).

Replaces the Flask ``current_app.task_queue`` / ``current_app.ops_queue``
extensions. The queue names and timeouts mirror the original ``config.py`` RQ
settings so existing workers and enqueued jobs keep working unchanged.
"""
import os

from redis import Redis
from rq import Queue


TASK_QUEUE_NAME = "cedars"
OPS_QUEUE_NAME = "ops"
JOB_TIMEOUT = 3600
OPERATION_TIMEOUT = 86400


def get_redis_url():
    """Build the Redis URL from environment (mirrors ``config.FULL_REDIS_URL``)."""
    protocol = os.getenv("REDIS_PROTOCOL", "redis")
    token = os.getenv("AUTH_TOKEN", "")
    host = os.getenv("REDIS_URL")
    port = os.getenv("REDIS_PORT")
    return f"{protocol}://:{token}@{host}:{port}/0"


redis_conn = Redis.from_url(get_redis_url())

task_queue = Queue(TASK_QUEUE_NAME, connection=redis_conn, default_timeout=JOB_TIMEOUT)
ops_queue = Queue(OPS_QUEUE_NAME, connection=redis_conn, default_timeout=OPERATION_TIMEOUT)
