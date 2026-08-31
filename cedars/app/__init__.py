"""CEDARS application package.

The web layer is served by FastAPI (see :mod:`app.main`). This package init is
intentionally minimal so that importing the data / NLP / adjudication modules
(``app.database``, ``app.nlpprocessor``, ``app.adjudication_handler`` ...) never pulls
in the web framework. This also keeps the RQ workers lightweight.
"""
import sys
import logging

from loguru import logger


def setup_logging():
    """Configure Loguru as the primary logger and tame noisy stdlib loggers."""
    # Remove default Loguru handler (avoid duplicate logs)
    logger.remove()

    # Setup Loguru logging (DEBUG and above)
    logger.add(sys.stdout,
               format="{time} {level} {message}",
               level="DEBUG",
               colorize=True)

    # Suppress werkzeug request logs (harmless if werkzeug is unused)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # Redirect Python's `logging` module logs to Loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            level = (logger.level(record.levelname).name
                     if record.levelname in logger._core.levels else "DEBUG")
            logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG)

    # Suppress RQ worker debug logs
    logging.getLogger("rq.worker").setLevel(logging.DEBUG)
    logging.getLogger("rq.queue").setLevel(logging.DEBUG)