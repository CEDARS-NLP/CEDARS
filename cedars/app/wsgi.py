"""Create flask application"""

import os
import sys
import logging
from dotenv import dotenv_values, load_dotenv
from loguru import logger
from . import create_app
from . import db

load_dotenv()

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")

app = create_app(f"config.{environment.title()}")

if __name__ == '__main__':
    # host should be 0.0.0.0 for docker to work
    logger.info(f"Starting app in {environment} mode")
    app.run(host=config['HOST'], port=config['PORT'], debug=True)
