"""Initialize database connection."""
from flask_pymongo import PyMongo
from minio import Minio
from dotenv import dotenv_values

config = dotenv_values(".env")
mongo = PyMongo()


client = Minio(
    f'{config["MINIO_HOST"]}:{config["MINIO_PORT"]}',
    access_key=config["MINIO_ACCESS_KEY"],
    secret_key=config["MINIO_SECRET_KEY"],
    secure=False # should be true for prod or AWS
)

if not client.bucket_exists("cedars"):
    client.make_bucket("cedars")
else:
    print("Bucket 'cedars' already exists")