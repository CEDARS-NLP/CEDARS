import os
import datetime
import pytest
from dotenv import dotenv_values
import sqlalchemy
from app import db
from app.database import db_session, db_engine, Base
from app.sqlalchemy_tables import INFO, PATIENTS, NOTES, QUERY
from app.sqlalchemy_tables import ANNOTATIONS, COMMENTS, USERS

# Drop all tables from database
if sqlalchemy.inspect(db_engine).has_table("INFO"):
    INFO.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("PATIENTS"):
    PATIENTS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("NOTES"):
    NOTES.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("QUERY"):
    QUERY.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("ANNOTATIONS"):
    ANNOTATIONS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("COMMENTS"):
    COMMENTS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("USERS"):
    USERS.__table__.drop(db_engine)


def test_create_project():
    db.create_project("proj_name", "investigator_name", "version_2")

    ## TODO : test if the schema of tables are correct

def test_get_info():
    retrieved_data = db.get_info()

    expected_data = {'cedars_version': 'version_2', 'project_name': 'proj_name', 'investigator_name': 'investigator_name'}

    for key in expected_data:
        assert key in retrieved_data
        assert retrieved_data[key] == expected_data[key]
    
    assert 'creation_time' in retrieved_data
    assert type(retrieved_data['creation_time']) == type(datetime.datetime())