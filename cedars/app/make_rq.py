import os
from dotenv import dotenv_values, load_dotenv
from app import create_app

load_dotenv()

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")

def create_rq_app():
    flask_app = create_app(f"config.{environment.title()}")
    rq_app = flask_app.extensions['rq']
    return rq_app