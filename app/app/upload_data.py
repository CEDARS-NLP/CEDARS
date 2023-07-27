import logging
from flask import Blueprint, render_template
from flask import redirect, session, request
from werkzeug.utils import secure_filename
import pandas as pd
from login_page import login_required, get_initials
from mongodb_client import DatabaseConnector


def allowed_data_file(filename):
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'json', 'parquet', 'pickle', 'pkl', 'xml'}
    
    extension = filename.split(".")[-1]

    return extension in ALLOWED_EXTENSIONS


def load_pandas_dataframe(filepath):
    extension = filepath.split(".")[-1]
    if extension == 'csv':
        return pd.read_csv(filepath)
    elif extension == 'xlsx':
        return pd.read_excel(filepath)
    elif extension == 'json':
        return pd.read_json(filepath)
    elif extension == 'parquet':
        return pd.read_parquet(filepath)
    elif extension == 'pickle' or extension == 'pkl':
        return pd.read_pickle(filepath)
    elif extension == 'xml':
        return pd.read_xml(filepath)

 # Pylint disabled due to naming convention.
def EMR_to_mongodb(db_conn, filepath): #pylint: disable=C0103
    """
    This function is used to open a csv file and load it's contents into the mongodb database.
    
    Args:
        filepath (str) : The path to the file to load data from. 
            For valid file extensions refer to the allowed_data_file function above.

    Returns:
        None

    Raises:
        None
    """
    if not allowed_data_file(filepath):
        return 
    
    data_frame = load_pandas_dataframe(filepath)
    if data_frame is None:
        return

    id_list = data_frame["patient_id"].unique()
    logging.info("Starting document migration to mongodb database.")
    for i, p_id in enumerate(id_list):
        documents = data_frame[data_frame["patient_id"] == p_id]

        db_conn.upload_notes(documents)

        logging.info("Documents uploaded for patient #%s", str(i + 1))

    logging.info("Completed document migration to mongodb database.")

upload_page = Blueprint("upload_data", __name__)

@upload_page.route("/upload_data", methods=["GET", "POST"])
@login_required
def upload_data():
    """
    This is a flask function for the backend logic 
                    to upload a csv file to the database.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    db_conn = DatabaseConnector()
    
    user_name = session["user"]
    user_initials = get_initials(user_name)
    proj_name = db_conn.get_proj_name()

    if request.method == "GET":
        return render_template("upload_file.html", user_initials = user_initials, 
                            proj_name = proj_name)
    else:
        if "data_file1" not in request.files and "data_file2" not in request.files:
            return redirect("/upload_data")

        if "data_file1" in request.files:
            file = request.files["data_file1"]
            filename = user_name + "_" + secure_filename(file.filename)
            file_path = "static/csv_files/" + filename
            file.save(file_path)

            EMR_to_mongodb(db_conn, file_path)
            return redirect("/upload_query")

        return render_template("upload_file.html", user_initials = user_initials, 
                        proj_name = proj_name)

