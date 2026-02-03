"""Initialize database connection."""
import os
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
    minio_connection_type = os.getenv("MINIO_CONNECTION_TYPE", None)
    from . import db
    project_id = os.getenv("PROJECT_ID", None)
    project_info = db.get_info()
    if project_id is None and "project_id" in project_info:
        project_id = project_info["project_id"]

    if minio_connection_type is not None and minio_connection_type == "AWS_S3":
        g.bucket_name = os.getenv("S3_BUCKET_NAME")
        if not g.bucket_name:
            raise RuntimeError("S3_BUCKET_NAME not set in environment")
        if minio_client is None:
            minio_client = g.minio = Minio(
                endpoint=f'{os.getenv("MINIO_HOST")}:{os.getenv("MINIO_PORT")}',
                access_key=os.getenv("MINIO_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_SECRET_KEY"),
                secure=False  # true only if you add TLS in front of MinIO
            )

            # IMPORTANT:
            # In S3 gateway mode, MinIO does NOT create buckets.
            # The bucket already exists in AWS S3.
            if not minio_client.bucket_exists(g.bucket_name):
                raise RuntimeError(
                    f"S3 bucket '{g.bucket_name}' does not exist or credentials are invalid"
                )
            else:
                logger.info(f"Bucket '{g.bucket_name}' already exists")

            logger.info(f"Connected to S3 bucket '{g.bucket_name}' via MinIO")
    else:
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
