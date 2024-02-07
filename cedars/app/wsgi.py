"""Create flask application"""

import os
import sys
from dotenv import dotenv_values, load_dotenv
from loguru import logger
from cedars.app import create_app

load_dotenv()

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")

logger.remove()
logger.add("cedars.log", enqueue=True, rotation="10 MB")
logger.add(sys.stderr, format="{time} {level} {message}", filter="cedars", level="INFO")

app = create_app(f"cedars.config.{environment.title()}")

if __name__ == '__main__':
    # host should be 0.0.0.0 for docker to work
    logger.info(f"Starting app in {environment} mode")
    app.run(host=config['HOST'], debug=True)
