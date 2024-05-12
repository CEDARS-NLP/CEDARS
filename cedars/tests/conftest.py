import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch
from flask import request
from dotenv import load_dotenv
from mongomock import MongoClient
from redis import Redis
import fakeredis
from flask_login import FlaskLoginClient
from app.auth import User


load_dotenv()
test_data = pd.read_csv(Path(__file__).parent / "simulated_patients.csv")


@pytest.fixture(scope="session")
def cedars_app():
    environment = 'test'
    with patch.object(Redis, 'from_url', fakeredis.FakeStrictRedis.from_url):
        from app import create_app
        cedars_app = create_app(f"config.{environment.title()}")
        with cedars_app.test_request_context():
            with patch('flask_pymongo.PyMongo') as mock_pymongo:
                mock_pymongo.return_value = MongoClient()
                yield cedars_app


@pytest.fixture(scope="session")
def db(cedars_app):
    from app import db
    db.create_project(project_name="test_project",
                      investigator_name="test_investigator",
                      cedars_version="test_version")
    db.add_user("test_user", "test_password")
    db.upload_notes(test_data)
    yield db


@pytest.fixture(scope="session")
def client(cedars_app):
    user = User({"_id": "000102030405060708090a0b",
                 "user": "test_user",
                 "password": "test_password",
                 "is_admin": True})
    with cedars_app.test_request_context():
        cedars_app.test_client_class = FlaskLoginClient
        with patch.object(request, 'form') as mock_form:
            mock_form.return_value.username = "test_user"
            mock_form.return_value.password = "test_password"
            mock_form.return_value.confirm_password = "test_password"
            mock_form.return_value.is_admin = True
            client = cedars_app.test_client(user=user)
            client.post("/auth/register")
            client.post("/auth/login")
            yield client


@pytest.fixture
def runner(cedars_app):
    return cedars_app.test_cli_runner()
