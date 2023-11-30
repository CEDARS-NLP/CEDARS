"""
Basic configurations for the app
"""
from datetime import timedelta

from dotenv import dotenv_values

config = dotenv_values("cedars/.env")


class Base:  # pylint: disable=too-few-public-methods
    """
    Base Config - all the common (no dependent on env) 
    configurations go here
    """
    SECRET_KEY = config['SECRET_KEY']
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)
    MONGO_URI = f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}@{config["DB_HOST"]}:{config["DB_PORT"]}/{config["DB_NAME"]}?authSource=admin'


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
    CACHE_REDIS_URL = 'redis://redis:6379/0'
    CACHE_KEY_PREFIX = 'app_'
