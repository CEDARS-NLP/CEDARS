import os
from flask_application import create_app

app = create_app("PYCEDARS")


if not os.path.isdir('static/csv_files'):
    os.mkdir('static/csv_files')

if __name__ == '__main__':
    app.run(host='0.0.0.0')
