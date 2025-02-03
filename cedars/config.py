"""
Basic configurations for the app
"""
from datetime import timedelta

from dotenv import dotenv_values
from redis import Redis

config = dotenv_values(".env")


class Base:  # pylint: disable=too-few-public-methods
    """
    Base Config - all the common (no dependent on env)
    configurations go here

    The socketTimeout might cause timeout for larger inserts

    TODO: make the bulk writes chunked?
    """
    SECRET_KEY = config['SECRET_KEY']
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)

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
