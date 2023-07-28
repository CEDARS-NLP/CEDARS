import os
from flask_application import create_app
from dotenv import load_dotenv

load_dotenv()

app = create_app("PYCEDARS")


if not os.path.isdir('static/csv_files'):
    os.mkdir('static/csv_files')

if __name__ == '__main__':
    app.run(host=os.getenv('HOST'), debug=True)
