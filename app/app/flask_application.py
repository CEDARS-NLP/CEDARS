"""
This file contatins the flask backend code to run the CEDARS web interface.
"""
from tempfile import mkdtemp
import os
from flask import Flask, render_template, session
from flask import request, redirect, url_for, send_file
from flask_session import Session
from werkzeug.utils import secure_filename
import pandas as pd
from mongodb_client import DatabaseConnector
from NLP_processor import NLP_processor
from session_functions import update_session_variables
from login_page import get_initials, login_required


def create_app(db_name):
    """
    """
    db_conn = DatabaseConnector(db_name, "CEDARS demo", "", 0.1)
    nlp_processor = NLP_processor("en_core_sci_lg")
    app = Flask(__name__)

    # Ensure templates are auto-reloaded
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    @app.after_request
    def after_request(response):
        """
        Ensure responses aren't cached
        """
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response


    # Configure session to use filesystem (instead of signed cookies)
    app.config["SESSION_FILE_DIR"] = mkdtemp()
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_TYPE"] = "filesystem"
    Session(app)

    from login_page import login_page, login_manager
    login_manager.init_app(app)
    app.register_blueprint(login_page)

    from upload_data import upload_page
    app.register_blueprint(upload_page)

    from upload_query import upload_query_page
    app.register_blueprint(upload_query_page)

    from add_user_page import add_user_page
    app.register_blueprint(add_user_page)

    from project_details_page import proj_details_page
    app.register_blueprint(proj_details_page)

    from adjudicate_records_page import adjudicate_records_page
    app.register_blueprint(adjudicate_records_page)

    from save_adjudications import save_adjudications_page
    app.register_blueprint(save_adjudications_page)

    from stats import stats_page
    app.register_blueprint(stats_page)

    from download_annotations import download_annotations_page
    app.register_blueprint(download_annotations_page)
    
    @app.route("/no_remaining_annotations", methods=["GET", "POST"])
    @login_required
    def no_remaining_annotations():
        """
        This is a flask function for the backend logic 
                        for the no_remaining_annotations page.
        Runs if all annotations of a patient have been completed.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        update_session_variables(db_conn)
        return redirect("/")
        
    

    @app.route("/search_patient", methods=["POST"])
    @login_required
    def search_patient():
        """
        This is a flask function for the backend logic 
                        for the search_patient page.
        There is no dedicated page for this logic, we simply update the 
                            session variables and go back to the main page.
        Runs if all annotations of a patient have been completed.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        update_session_variables(db_conn, int(request.form["patient_id"]))
        return redirect("/")
    
    @app.route('/', methods=["GET"])
    @login_required
    def homepage():
        proj_name = db_conn.get_proj_name()
        user_name = session["user"]
        user_initials = get_initials(user_name)

        return render_template('index.html', proj_name = proj_name,
                                user_initials = user_initials)

    return app