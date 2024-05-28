from pymongo import MongoClient
from dotenv import dotenv_values

config = dotenv_values(".env")

MONGO_URI = (
        f'mongodb://{config["DB_USER"]}:{config["DB_PWD"]}'
        f'@{config["DB_HOST"]}:{config["DB_PORT"]}/'
        f'{config["DB_NAME"]}?{config["DB_PARAMS"]}'
    )

print(MONGO_URI)
client = MongoClient(MONGO_URI)
db = client.sample_database
col = db.sample_collection
col.insert_one({"name": "John Doe"})
x = col.find_one()
print(x)
client.close()
