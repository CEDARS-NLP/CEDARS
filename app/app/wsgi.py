"""
This file runs the flask backend server.
"""
import os
from dotenv import load_dotenv
from flask_application import create_app
from mongodb_client import DatabaseConnector


load_dotenv()

app = create_app(os.getenv("DB_NAME"))

db_conn = DatabaseConnector()
db_conn.remove_all_locked()


if not os.path.isdir('static/csv_files'):
    os.mkdir('static/csv_files')

if __name__ == '__main__':
    app.run(host=os.getenv('HOST'), debug=True)
