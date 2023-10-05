import os
import pandas as pd
import pytest
from pathlib import Path
from app import create_app
from app import db

test_data = pd.read_csv(Path(__file__).parent / "simulated_patients.csv")

@pytest.fixture
def app():
    environment = os.getenv('ENV', 'test')
    app = create_app(f"app.config.{environment.title()}")

    with app.app_context():
        db.create_project(project_name="testing",
                      investigator_name="tester",
                      cedars_version="test")

        db.upload_notes(test_data)

    yield app

    db.drop_database("Test")


class AuthActions(object):
    def __init__(self, client):
        self._client = client

    def register(self, username='test', password='test'):
        return self._client.post(
            '/auth/register',
            data={'username': username, 'password': password}
        )

    def login(self, username='test', password='test'):
        return self._client.post(
            '/auth/login',
            data={'username': username, 'password': password}
        )

    def logout(self):
        return self._client.get('/auth/logout')


@pytest.fixture
def auth(client):
    return AuthActions(client)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
