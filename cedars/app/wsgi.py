"""Create flask application"""
import os

from dotenv import load_dotenv
from loguru import logger

from config import config
from . import create_app

load_dotenv()

environment = os.getenv('ENV', 'local')

app = create_app(f"config.{environment.title()}")

if __name__ == '__main__':
    # host should be 0.0.0.0 for docker to work
    logger.info(f"Starting app in {environment} mode")
    app.run(host=config['HOST'], port=config['PORT'], debug=True)
