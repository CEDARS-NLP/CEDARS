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
    MONGO_URI = f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}@{config["DB_HOST"]}:{config["DB_PORT"]}/{config["DB_NAME"]}?authSource=admin'
    RQ = {
        "redis_url": f'redis://{config["REDIS_URL"]}:{config["REDIS_PORT"]}/0',
        "queue_name": "cedars"
    }


class Local(Base):  # pylint: disable=too-few-public-methods
    """Local Config - for local development"""
    CACHE_TYPE = 'SimpleCache'
    DEBUG = True


class Test(Base):  # pylint: disable=too-few-public-methods
    """Test Config - for running tests"""
    CACHE_TYPE = 'SimpleCache'
    TESTING = True
    MONGO_URI = f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}@{config["DB_HOST"]}:{config["DB_PORT"]}/test?authSource=admin'



class Dev(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'


class Prod(Base):  # pylint: disable=too-few-public-methods
    """Dev Config - for deplaying to dev"""
    CACHE_TYPE = 'RedisCache'