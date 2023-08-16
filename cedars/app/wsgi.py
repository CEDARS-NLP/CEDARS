import os
from app import create_app

environment = os.getenv('ENV', 'local')


app = create_app(f"app.config.{environment.title()}")

if __name__ == '__main__':
    app.run(debug=True)
