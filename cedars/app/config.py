from datetime import timedelta

from dotenv import dotenv_values

config = dotenv_values(".env")


class Base(object):
    SECRET_KEY = config['SECRET_KEY']
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)
    MONGO_URI = f'mongodb://{config["DB_HOST"]}:{config["DB_PORT"]}/{config["DB_NAME"]}'


class Local(Base):
    CACHE_TYPE = 'SimpleCache'
    DEBUG = True


class Test(Base):
    CACHE_TYPE = 'SimpleCache'
    TESTING = True
    MONGO_URI = f'mongodb://{config["DB_HOST"]}:{config["DB_PORT"]}/Test'

class Dev(Base):
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = 'redis://redis:6379/0'
    CACHE_KEY_PREFIX = 'app_'
