"""RQ worker entrypoint (framework-agnostic).

Usage: ``python -m app.make_rq task`` or ``python -m app.make_rq ops``.

Each project has its own queue (see :mod:`app.queues`). This supervisor process
discovers all projects from the global registry and runs an RQ Worker process
listening on all active project queues using the admin Redis connection.
Discovery is repeated on an interval so newly created or deleted projects cause
the worker process to be cleanly restarted with the updated queue list.
"""
import argparse
import multiprocessing
import time

from dotenv import load_dotenv
from loguru import logger
from rq import Worker

from . import setup_logging
from .database import get_global_engine
from .database.db_projects import list_projects
from .queues import (
    JOB_TIMEOUT,
    OPERATION_TIMEOUT,
    OPS_QUEUE_PREFIX,
    TASK_QUEUE_PREFIX,
    ProjectQueue,
    get_admin_redis,
    ops_queue_name,
    task_queue_name,
)

load_dotenv()

DISCOVERY_INTERVAL_SECONDS = 30


def _known_project_ids() -> set:
    return {project.project_id for project in list_projects(get_global_engine())}


def _run_worker_process(queue_names: list, worker_type: str) -> None:
    setup_logging()
    admin_redis = get_admin_redis()
    timeout = JOB_TIMEOUT if worker_type == "task" else OPERATION_TIMEOUT
    queues = [
        ProjectQueue(name, connection=admin_redis, default_timeout=timeout)
        for name in queue_names
    ]
    if not queues:
        dummy_name = f"{TASK_QUEUE_PREFIX if worker_type == 'task' else OPS_QUEUE_PREFIX}-default"
        queues = [ProjectQueue(dummy_name, connection=admin_redis, default_timeout=timeout)]

    logger.info(f"Starting {worker_type} worker process listening on queues: {[q.name for q in queues]}")
    Worker(queues, connection=admin_redis).work()


def run_workers(worker_type: str) -> None:
    """Monitor project list and supervise worker process listening on active queues."""
    current_pids = None
    worker_proc = None

    try:
        while True:
            pids = _known_project_ids()
            if pids != current_pids:
                if worker_proc is not None and worker_proc.is_alive():
                    logger.info("Project list changed. Restarting worker process...")
                    worker_proc.terminate()
                    worker_proc.join(timeout=5)
                    if worker_proc.is_alive():
                        worker_proc.kill()

                current_pids = pids
                queue_names = [
                    task_queue_name(pid) if worker_type == "task" else ops_queue_name(pid)
                    for pid in sorted(pids)
                ]

                worker_proc = multiprocessing.Process(
                    target=_run_worker_process,
                    args=(queue_names, worker_type),
                    daemon=True,
                )
                worker_proc.start()

            time.sleep(DISCOVERY_INTERVAL_SECONDS)
    finally:
        if worker_proc is not None and worker_proc.is_alive():
            worker_proc.terminate()
            worker_proc.join(timeout=2)


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Create RQ worker")
    parser.add_argument("worker", choices=["task", "ops"], help="Worker type")
    args = parser.parse_args()
    run_workers(args.worker)


