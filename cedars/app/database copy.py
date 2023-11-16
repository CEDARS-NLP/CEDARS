"""Initialize database connection."""

from minio import Minio
from dotenv import dotenv_values
import sqlalchemy
import os

config = dotenv_values(".env")

db_type = str(config["DB_TYPE"])

if db_type == "mongo":
    from flask_pymongo import PyMongo
    db_conn = PyMongo()
elif db_type == "sqlite3":
    import sqlite3

    db_name = config["DB_NAME"]
    # If a database with the given name does not exist, we create a database file in the app directory
    if f'{db_name}.db' not in os.listdir():
        sqlite3.connect(f'{db_name}.db')
    
    dbEngine=sqlalchemy.create_engine(f'sqlite:///{db_name}.db')
    
    db_conn = dbEngine.connect()
else:
    raise Exception("Invalid database type in environment variables.")



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