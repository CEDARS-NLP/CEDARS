import argparse

from dotenv import load_dotenv
from rq import Worker

from . import create_app

load_dotenv()


def create_rq_app():
    flask_app = create_app(f"config.Base")
    rq_app = flask_app.extensions['rq']
    return rq_app


def create_task_worker():
    rq_app = create_rq_app()
    with rq_app.app_context():
        worker = Worker(rq_app.task_queue,
                        connection=rq_app.redis
                        )
        worker.work()


def create_ops_worker():
    rq_app = create_rq_app()
    with rq_app.app_context():
        worker = Worker(rq_app.ops_queue,
                        connection=rq_app.redis,
                        )
        worker.work()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create RQ worker")
    parser.add_argument("worker", choices=["task", "ops"], help="Worker type")
    args = parser.parse_args()
    if args.worker == "task":
        create_task_worker()
    else:
        create_ops_worker()
