import os
import pandas as pd
import pytest
from pathlib import Path
from cedars.app import create_app
from cedars.app import db

test_data = pd.read_csv(Path(__file__).parent / "simulated_patients.csv")


@pytest.fixture(scope='session', autouse=True)
def app():
    environment = 'test'
    cedars_app = create_app(f"cedars.config.{environment.title()}")

    with cedars_app.app_context():
        db.create_project(
            project_name="testing",
            investigator_name="tester",
            cedars_version="test")

        db.upload_notes(test_data)

    yield cedars_app

    db.drop_database("test")


# class AuthActions(object):
#     def __init__(self, client):
#         self._client = client

#     def register(self, username='test', password='test'):
#         return self._client.post(
#             '/auth/register',
#             data={'username': username, 'password': password}
#         )

#     def login(self, username='test', password='test'):
#         return self._client.post(
#             '/auth/login',
#             data={'username': username, 'password': password}
#         )

#     def logout(self):
#         return self._client.get('/auth/logout')


@pytest.fixture()
def client(app):
    return app.test_client()


# @pytest.fixture()
# def auth(client):
#     return AuthActions(client)


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
