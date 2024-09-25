"""Initialize database connection."""
import flask_pymongo
from minio import Minio
from werkzeug.local import LocalProxy
from dotenv import dotenv_values
from flask import current_app, g
from loguru import logger


config = dotenv_values(".env")


def get_mongo():
    # https://pymongo.readthedocs.io/en/stable/faq.html#is-pymongo-fork-safe
    mongo = flask_pymongo.PyMongo(current_app)
    return mongo


def get_minio():
    minio = getattr(g, "minio", None)
    from . import db
    project_id = os.getenv("PROJECT_ID", None)
    project_info = db.get_info()
    if project_id is None and "project_id" in project_info:
        project_id = project_info["project_id"]
        
    g.bucket_name = f"cedars-{project_id}"
    if minio is None:
        minio = g.minio = Minio(
            f'{config["MINIO_HOST"]}:{config["MINIO_PORT"]}',
            access_key=config["MINIO_ACCESS_KEY"],
            secret_key=config["MINIO_SECRET_KEY"],
            secure=False  # should be true for prod or AWS
        )
        if not minio.bucket_exists(g.bucket_name):
            minio.make_bucket(g.bucket_name)
        else:
            logger.info(f"Bucket '{g.bucket_name}' already exists")

    return minio


mongo = LocalProxy(get_mongo)
minio = LocalProxy(get_minio)
