import os
from dotenv import dotenv_values
from app import create_app

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")

app = create_app(f"app.config.{environment.title()}")

if __name__ == '__main__':
    # host should be 0.0.0.0 for docker to work
    app.run(host=config['HOST'])
