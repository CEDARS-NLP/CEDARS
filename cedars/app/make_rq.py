import os
from dotenv import dotenv_values, load_dotenv
from app import create_app
from rq import Worker

load_dotenv()

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")

def create_rq_app():
    flask_app = create_app(f"config.{environment.title()}")
    rq_app = flask_app.extensions['rq']
    return rq_app

def create_worker():
    rq_app = create_rq_app()
    with rq_app.app_context():
        worker = Worker(rq_app.task_queue,
                        connection=rq_app.redis,
                        )
        worker.work()

if __name__ == "__main__":
    create_worker()