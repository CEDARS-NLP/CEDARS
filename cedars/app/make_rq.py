"""RQ worker entrypoint (framework-agnostic).

Usage: ``python -m app.make_rq task`` or ``python -m app.make_rq ops``.

Workers no longer build a Flask app; they connect to Redis directly via
:mod:`app.queues`. Each enqueued job binds its own project database context
(see :mod:`app.tasks`), so the workers stay project-agnostic.
"""
import argparse

from dotenv import load_dotenv
from rq import Worker

from . import setup_logging
from .queues import redis_conn, task_queue, ops_queue

load_dotenv()


def create_task_worker():
    """Run a worker on the NLP task queue."""
    Worker([task_queue], connection=redis_conn).work()


def create_ops_worker():
    """Run a worker on the operations queue."""
    Worker([ops_queue], connection=redis_conn).work()


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Create RQ worker")
    parser.add_argument("worker", choices=["task", "ops"], help="Worker type")
    args = parser.parse_args()
    if args.worker == "task":
        create_task_worker()
    else:
        create_ops_worker()

