import os
from pymongo import MongoClient
from dotenv import dotenv_values,load_dotenv

load_dotenv()
# config = dotenv_values(".env")

MONGO_URI = (
        f'{os.getenv("DB_PROTOCOL", "mongodb")}://{os.getenv("DB_USER")}:{os.getenv("DB_PWD")}'
        f'@{os.getenv("DB_HOST")}:{os.getenv("DB_PORT")}/'
        f'{os.getenv("DB_NAME")}?{os.getenv("DB_PARAMS")}'
    )

print(MONGO_URI)
client = MongoClient(MONGO_URI)
db = client.sample_database
col = db.sample_collection
col.insert_one({"name": "John Doe"})
x = col.find_one()
print(x)
client.close()
