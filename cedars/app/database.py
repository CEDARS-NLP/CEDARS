"""Initialize database connection."""
import os
import flask_pymongo
import boto3
from werkzeug.local import LocalProxy
from dotenv import dotenv_values, load_dotenv
from flask import current_app, g
from loguru import logger
from botocore.exceptions import ClientError


load_dotenv()


def get_mongo():

    # https://pymongo.readthedocs.io/en/stable/faq.html#is-pymongo-fork-safe
    mongo = flask_pymongo.PyMongo(current_app)

    return mongo


def get_s3():

    from . import db
    project_id = os.getenv("PROJECT_ID", None)
    project_info = db.get_info()
    if project_id is None and "project_id" in project_info:
        project_id = project_info["project_id"]
   
    g.bucket_name = os.getenv("S3_BUCKET") 
    aws_region = os.getenv("REGION")

    # Check if S3 client already exists in the global context
    s3 = getattr(g, "s3", None)
    #Initialize Boto3.client type S3 object
    if s3 is None:
        s3 = g.s3 = boto3.client(
            "s3",
            region_name=aws_region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), 
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), 
        )
    
    # Ensure the bucket exists or throw an error
    try:
        # Check if bucket exists
        s3.head_bucket(Bucket=g.bucket_name)
        logger.info(f"Bucket '{g.bucket_name}' already exists in AWS S3")

    except s3.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        # 404 means it doesn't exist
        if error_code == '404':
            logger.error(f"Bucket does not exist: {e}")
            raise
        else:
            logger.error(f"Error checking if bucket exists: {e}")
            raise

    return s3

def get_s3_resource():

    g.bucket_name = os.getenv("S3_BUCKET") 
    aws_region = os.getenv("REGION")

    # Check if S3 resource is already exists in the global context
    s3_resource = getattr(g,"s3_resource",None)

    #Initialize Boto3.Resource type S3 object for some of the operations    
    if s3_resource is None:
        s3_resource = g.s3_resource = boto3.resource(
            "s3",
            region_name=aws_region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), 
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), 
        )
    
    # Ensure the bucket exists or throw an error
    try:
        # Check if bucket exists
        # s3_resource.head_bucket(Bucket=g.bucket_name)
        s3_resource.Bucket(g.bucket_name)
        logger.info(f"Bucket '{g.bucket_name}' already exists in AWS S3")

    except ClientError as e:
        error_code = e.response['Error']['Code']
        # 404 means it doesn't exist
        if error_code == '404':
            logger.error(f"Bucket does not exist: {e}")
            raise
        else:
            logger.error(f"Error checking if bucket exists: {e}")
            raise

    return s3_resource
    
mongo = LocalProxy(get_mongo)
s3=LocalProxy(get_s3)
s3_resource = LocalProxy(get_s3_resource)
