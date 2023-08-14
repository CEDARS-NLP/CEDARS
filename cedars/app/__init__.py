"""
Entrypoint for the flask application.
"""

__version__ = "0.1.0"
__author__ = "Rohan Singh"

from flask_login import login_required, current_user
from flask import Flask, redirect, url_for, render_template, session

from flask_pymongo import PyMongo
from faker import Faker

mongo = PyMongo()
fake = Faker()


def create_app(config_filename):
    app = Flask(__name__)
    app.config.from_object(config_filename)

    mongo.init_app(app)
    

    from . import db
    db.create_project(project_name=fake.slug(),
                      investigator_name=fake.name(),
                      cedars_version=__version__)
    
    from . import auth
    auth.login_manager.init_app(app)
    app.register_blueprint(auth.bp)

    from . import ops
    app.register_blueprint(ops.bp)

    from . import stats
    app.register_blueprint(stats.bp)

# # from flask_caching import Cache
# import os
# from flask_login import login_required
# from flask_session import Session
# from flask_pymongo import PyMongo
# from flask import (
#     Flask,
#     g,
#     request,
#     session,
#     url_for,
#     redirect,
#     render_template)


# def create_app(test_config=None):
#     """create and configure the app"""

#     app = Flask(__name__, instance_relative_config=True)
#     app.config.from_mapping(
#         MONGO_URI=f"mongodb://localhost:27017/cedars",
#         TEMPLATES_AUTO_RELOAD=True,
#         SECRET_KEY="dedsdsdsdv"
#     )

#     # if test_config is None:
#     #     # load the instance config, if it exists, when not testing
#     #     # app.config.from_pyfile('config.py', silent=True)
#     #     pass
#     # else:
#     #     # load the test config if passed in
#     #     app.config.from_mapping(test_config)

#     # Ensure templates are auto-reloaded
#     # app.config["TEMPLATES_AUTO_RELOAD"] = True

#     try:
#         os.makedirs(app.instance_path)
#     except OSError as exc:
#         print(exc)

#     from .auth import login_manager, get_initials
#     login_manager.init_app(app)
#     Session(app)
#     from . import auth
#     app.register_blueprint(auth.bp)
    
#     PyMongo(app)
    
#     from .mongodb_client import MongoConnector
#     @app.route("/search_patient", methods=["POST"])
#     @login_required
#     def search_patient():
#         """
#         This is a flask function for the backend logic 
#         for the search_patient page.
#         There is no dedicated page for this logic, we simply update the 
#         session variables and go back to the main page.
#         Runs if all annotations of a patient have been completed.
#         """

#         # Checks if the patient ID is valid
#         # If not redirects to adjudicate_records with error msg
#         try:
#             int(request.form["patient_id"])
#         except:
#             session["hasBeenLocked"] = True
#             return redirect("/adjudicate_records")

#         # makes sure that the current patient is not locked
#         status = MongoConnector().get_patient_lock_status(int(request.form["patient_id"]))
#         print(status, flush=True)
#         if status is None or status is True:
#             # Set to True if patient that has been searched for is locked
#             session["hasBeenLocked"] = True
#         else:
#             update_session_variables(app.config['DATABASE'], int(request.form["patient_id"]))

#         return redirect("/adjudicate_records")

    @app.route('/', methods=["GET"])
    @login_required
    def homepage():
        return render_template('index.html', **db.get_info())

    return app
