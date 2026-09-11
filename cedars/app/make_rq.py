"""RQ worker entrypoint (framework-agnostic).

Usage: ``python -m app.make_rq task`` or ``python -m app.make_rq ops``.

Each project has its own queue (see :mod:`app.queues`), so this process
discovers every project from the global registry and runs one ``Worker``
thread per project queue. Discovery is repeated on an interval so projects
created after this process starts are picked up without a restart; workers
for deleted projects are simply left idling on an empty queue.
"""
import argparse
import threading
import time

from dotenv import load_dotenv
from loguru import logger
from rq import Worker

from . import setup_logging
from .database import get_global_engine
from .database.db_projects import list_projects
from .queues import get_ops_queue, get_task_queue

load_dotenv()

DISCOVERY_INTERVAL_SECONDS = 30


def _known_project_ids() -> set:
    return {project.project_id for project in list_projects(get_global_engine())}


def _run_worker(queue) -> None:
    Worker([queue], connection=queue.connection).work()


def run_workers(queue_factory) -> None:
    """Discover every project and keep one worker thread per project queue running."""
    started: set = set()
    while True:
        for project_id in _known_project_ids():
            if project_id in started:
                continue
            started.add(project_id)
            queue = queue_factory(project_id)
            threading.Thread(target=_run_worker, args=(queue,), daemon=True,
                            name=f"rq-worker-{queue.name}").start()
        time.sleep(DISCOVERY_INTERVAL_SECONDS)


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Create RQ worker")
    parser.add_argument("worker", choices=["task", "ops"], help="Worker type")
    args = parser.parse_args()
    run_workers(get_task_queue if args.worker == "task" else get_ops_queue)


