"""
Basic configurations for the app
"""
import os
from datetime import timedelta
from urllib.parse import quote_plus
from dotenv import dotenv_values,load_dotenv
from redis import Redis


load_dotenv()
config = dotenv_values(".env")

FULL_REDIS_URL = f'{os.getenv("REDIS_PROTOCOL")}://:{os.getenv("AUTH_TOKEN")}@{os.getenv("REDIS_URL")}:{os.getenv("REDIS_PORT")}/0'


class Base:  # pylint: disable=too-few-public-methods
    """
    Base Config - all the common (no dependent on env)
    configurations go here

    The socketTimeout might cause timeout for larger inserts

    TODO: make the bulk writes chunked?
    """
    SECRET_KEY = os.getenv('SECRET_KEY')
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)

    db_replica_set = os.getenv("DB_REPLICA_SET")
    if db_replica_set is not None:
        MONGO_URI = (
            f'{os.getenv("DB_PROTOCOL", "mongodb")}://{os.getenv("DB_USER")}:{quote_plus(os.getenv("DB_PWD"))}'
            f'@{db_replica_set}/'
            f'{os.getenv("DB_NAME")}?{os.getenv("DB_PARAMS")}'
        )
    else:
        MONGO_URI = (
            f'{os.getenv("DB_PROTOCOL", "mongodb")}://{os.getenv("DB_USER")}:{quote_plus(os.getenv("DB_PWD"))}'
            f'@{os.getenv("DB_HOST")}:{os.getenv("DB_PORT")}/'
            f'{os.getenv("DB_NAME")}?{os.getenv("DB_PARAMS")}'
        )

    
    RQ = {
        "redis_url": FULL_REDIS_URL,
        "task_queue_name": "cedars",
        "ops_queue_name": "ops",
        "job_timeout": 3600,
        "operation_timeout": 86400
    }

class Local(Base):  # pylint: disable=too-few-public-methods
    """Local Config - for local development"""
    DEBUG = True


class Test(Base):  # pylint: disable=too-few-public-methods
    """Test Config - for running tests"""
    CACHE_TYPE = 'SimpleCache'


class Dev(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'


class Prod(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'
