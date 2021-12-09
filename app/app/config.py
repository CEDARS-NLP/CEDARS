import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Base(object):
    SECRET_KEY = os.getenv('SECRET_KEY')
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)


class Local(Base):
    CACHE_TYPE = 'SimpleCache'


class Dev(Base):
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = 'redis://redis:6379/0'
    CACHE_KEY_PREFIX = 'app_'
