"""
Basic configurations for the app
"""
from datetime import timedelta

from dotenv import dotenv_values

config = dotenv_values(".env")


class Base:  # pylint: disable=too-few-public-methods
    """
    Base Config - all the common (no dependent on env)
    configurations go here
    """
    SECRET_KEY = config['SECRET_KEY']
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)
    MONGO_URI = MONGO_URI = (
    f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}'
    f'@{config["DB_HOST"]}:{config["DB_PORT"]}/'
    f'{config["DB_NAME"]}?'
    f'{config["DB_PARAMS"]}'
    f'&minPoolSize=5'
    f'&connectTimeoutMS=30000'
    f'&retryWrites=true'
    f'&socketTimeoutMS=20000'
    f'&serverSelectionTimeoutMS=5000'
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
    CACHE_TYPE = 'SimpleCache'
    DEBUG = True


class Test(Base):  # pylint: disable=too-few-public-methods
    """Test Config - for running tests"""
    CACHE_TYPE = 'SimpleCache'
    TESTING = True
    MONGO_URI = (f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}'
                 f'@{config["DB_HOST"]}:{config["DB_PORT"]}/'
                 'test?authSource=admin')


class Dev(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'


class Prod(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'
