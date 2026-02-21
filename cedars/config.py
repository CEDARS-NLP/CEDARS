"""
Basic configurations for the app

This module centralizes all configuration loading. Other modules should import
`config` from here rather than calling dotenv_values() directly.
"""
from datetime import timedelta

from dotenv import dotenv_values
from redis import Redis

# Load config once - other modules should import this
config = dotenv_values(".env")

# Required configuration variables (always required)
REQUIRED_CONFIG_BASE = [
    'SECRET_KEY',
    'REDIS_URL',
    'REDIS_PORT',
]

# Required for MongoDB backend
REQUIRED_CONFIG_MONGODB = [
    'DB_USER',
    'DB_PWD',
    'DB_HOST',
    'DB_PORT',
    'DB_NAME',
]

# Optional SQLite configuration
# SQLITE_DB_PATH - path to SQLite database file (default: cedars.db)


def validate_config():
    """Validate that all required configuration variables are present."""
    db_type = config.get("DB_TYPE", "mongodb").lower()

    required = REQUIRED_CONFIG_BASE.copy()
    if db_type == "mongodb":
        required.extend(REQUIRED_CONFIG_MONGODB)

    missing = [var for var in required if not config.get(var)]
    if missing:
        raise RuntimeError(
            f"Missing required configuration variables: {', '.join(missing)}. "
            f"Check your .env file against .env.sample"
        )


class Base:  # pylint: disable=too-few-public-methods
    """
    Base Config - all the common (no dependent on env)
    configurations go here

    The socketTimeout might cause timeout for larger inserts

    TODO: make the bulk writes chunked?
    """
    SECRET_KEY = config['SECRET_KEY']
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)
    SESSION_TYPE = 'redis'

    MONGO_URI = MONGO_URI = (
    f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}'
    f'@{config["DB_HOST"]}:{config["DB_PORT"]}/'
    f'{config["DB_NAME"]}?'
    f'{config["DB_PARAMS"]}'
    f'&maxPoolSize=50'
    f'&minPoolSize=5'
    f'&connectTimeoutMS=30000'
    f'&retryWrites=true'
    f'&socketTimeoutMS=20000'
    f'&serverSelectionTimeoutMS=20000'
    f'&heartbeatFrequencyMS=20000'
    f'&readPreference=primaryPreferred'
)
    RQ = {
        "redis_url": f'redis://{config["REDIS_URL"]}:{config["REDIS_PORT"]}/0',
        "task_queue_name": "cedars",
        "ops_queue_name": "ops",
        "job_timeout": 3600,
        "operation_timeout": 7200
    }

class Local(Base):  # pylint: disable=too-few-public-methods
    """Local Config - for local development"""
    DEBUG = True


class Test(Base):  # pylint: disable=too-few-public-methods
    """Test Config - for running tests"""
    TESTING = True
    SESSION_TYPE = 'redis'
    SESSION_KEY_PREFIX = "cedars:test:"
    SESSION_USE_SIGNER = True
    SESSION_PERMANENT = False
    SESSION_SERIALIZATION_FORMAT = "json"
    SESSION_REDIS = Redis.from_url(f'redis://{config["REDIS_URL"]}:{config["REDIS_PORT"]}/0')


class Dev(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    SESSION_TYPE = 'redis'
    SESSION_KEY_PREFIX = "cedars:"
    SESSION_USE_SIGNER = True
    SESSION_PERMANENT = False
    SESSION_SERIALIZATION_FORMAT = "json"
    SESSION_REDIS = Redis.from_url(f'redis://{config["REDIS_URL"]}:{config["REDIS_PORT"]}/0')


class Prod(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    SESSION_TYPE = 'redis'
    SESSION_KEY_PREFIX = "cedars:prod:"
    SESSION_USE_SIGNER = True
    SESSION_PERMANENT = False
    SESSION_SERIALIZATION_FORMAT = "json"
    SESSION_REDIS = Redis.from_url(f'redis://{config["REDIS_URL"]}:{config["REDIS_PORT"]}/0')
