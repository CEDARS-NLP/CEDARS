"""Initialize database connection."""
import flask_pymongo
from minio import Minio
from werkzeug.local import LocalProxy
from dotenv import dotenv_values
from flask import current_app, g


config = dotenv_values(".env")


def get_mongo():
    mongo = getattr(g, "mongo", None)

    if mongo is None:
        mongo = g.mongo = flask_pymongo.PyMongo(current_app)

    return mongo


mongo = LocalProxy(get_mongo)


def get_minio():
    minio = getattr(g, "minio", None)
    from . import db
    project_id = db.get_info()["project_id"]
    g.bucket_name = f"cedars-{project_id}"
    if minio is None:
        minio = g.minio = Minio(
            f'{config["MINIO_HOST"]}:{config["MINIO_PORT"]}',
            access_key=config["MINIO_ACCESS_KEY"],
            secret_key=config["MINIO_SECRET_KEY"],
            secure=False  # should be true for prod or AWS
        )
        if not minio.bucket_exists("cedars"):
            minio.make_bucket(g.bucket_name)
        else:
            print(f"Bucket '{g.bucket_name}' already exists")

    return minio
