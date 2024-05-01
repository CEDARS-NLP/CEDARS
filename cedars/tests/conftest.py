import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch
from flask import g
from mongomock import MongoClient
from redis import Redis
import fakeredis

test_data = pd.read_csv(Path(__file__).parent / "simulated_patients.csv")


@pytest.fixture(scope="session")
def cedars_app():
    environment = 'test'
    with patch.object(Redis, 'from_url', fakeredis.FakeStrictRedis.from_url):
        from app import create_app
        cedars_app = create_app(f"config.{environment.title()}")
        with cedars_app.app_context():
            g.mongo = MongoClient()
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
    yield cedars_app.test_client()


@pytest.fixture
def runner(cedars_app):
    return cedars_app.test_cli_runner()
