"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import os
import logging
from pathlib import Path
import pandas as pd
from flask import (
    Blueprint, render_template, send_file,
    redirect, session, request, url_for, flash,
    current_app
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from app import db
from app import NLP_processor
from .auth import admin_required





bp = Blueprint("ops", __name__, url_prefix="/ops")


def allowed_data_file(filename):
    """
    This function is used to check if a file has a valid extension for us to load tabular data from.

    Args:
        filepath (str) : The path to the file.
    Returns:
        (bool) : True if the file is of a supported type.
    """
    allowed_extensions = {'csv', 'xlsx', 'json', 'parquet', 'pickle', 'pkl', 'xml'}

    extension = filename.split(".")[-1]

    return extension in allowed_extensions


def allowed_image_file(filename):
    """
    This function checks if a file is of a valid image filetype.

    Args:
        filename (str) : Name of the file trying to be loaded.
    Returns:
        (bool) : True if this is a supported image file type.
    """
    allowed_extensions = {'png', 'jpg', 'jpeg'}

    extension = filename.split(".")[-1]

    return extension in allowed_extensions


@bp.route("/project_details", methods=["GET", "POST"])
@admin_required
def project_details():
    """
    This is a flask function for the backend logic
                    for the proj_details route.
    It is used by the admin to view and alter details of the current project.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    if request.method == "POST":
        project_name = request.form.get("project_name")
        db.update_project_name(project_name)
        flash(f"Project name updated to {project_name}.")

        if "project_logo" in request.files:
            file = request.files["project_logo"]
            if allowed_image_file(secure_filename(file.filename)):
                file.save(Path("app/static") / "project_logo.png")
                flash("Logo updated successfully.")

        return render_template("index.html", **db.get_info())

    return render_template("ops/project_details.html", **db.get_info())


def load_pandas_dataframe(filepath):
    """
    This function is used to load tabular data from a file into a pandas DataFrame.

    Args:
        filepath (str) : The path to the file to load data from.
            For valid file extensions refer to the allowed_data_file function above.
    Returns:
        (pandas DataFrame) : This is a dataframe with the data from the file.
    """
    extension = str(filepath).rsplit('.', maxsplit=1)[-1].lower()

    if extension == 'csv':
        return pd.read_csv(filepath)
    if extension == 'xlsx':
        return pd.read_excel(filepath)
    if extension == 'json':
        return pd.read_json(filepath)
    if extension == 'parquet':
        return pd.read_parquet(filepath)
    if extension in ['pickle', 'pkl']:
        return pd.read_pickle(filepath)
    if extension == 'xml':
        return pd.read_xml(filepath)

    return None

# Pylint disabled due to naming convention.
def EMR_to_mongodb(filepath): #pylint: disable=C0103
    """
    This function is used to open a csv file and load it's contents into the mongodb database.

    Args:
        filepath (str) : The path to the file to load data from.
        For valid file extensions refer to the allowed_data_file function above.
    Returns:
        None
    # """
    # if not allowed_data_file(filepath):
    #     return

    data_frame = load_pandas_dataframe(filepath)
    if data_frame is None:
        return

    id_list = data_frame["patient_id"].unique()
    logging.info("Starting document migration to mongodb database.")
    for i, p_id in enumerate(id_list):
        documents = data_frame[data_frame["patient_id"] == p_id]

        db.upload_notes(documents)

        logging.info("Documents uploaded for patient #%s", str(i + 1))

    logging.info("Completed document migration to mongodb database.")


@bp.route("/upload_data", methods=["GET", "POST"])
@admin_required
def upload_data():
    """
    This is a flask function for the backend logic to upload a file to the database.
    """

    # if not (session.get('is_admin') is True):
    #     return redirect("/")
    if request.method == "GET":
        return render_template("ops/upload_file.html", **db.get_info())

    if "data_file1" not in request.files and "data_file2" not in request.files:
        return redirect(url_for('ops.upload_data'))

    if "data_file1" in request.files:
        file = request.files["data_file1"]
        filename = current_user.username + "_" + secure_filename(file.filename)

        if not allowed_data_file(filename):
            return render_template("ops/upload_file.html", **db.get_info())

        file_path = Path("app/static") / filename
        file.save(file_path)
        EMR_to_mongodb(file_path)
        flash(f"{filename} uploaded successfully.")
        return redirect(url_for('ops.upload_query'))

    return render_template("ops/upload_file.html", **db.get_info())


@bp.route("/upload_query", methods=["GET", "POST"])
@admin_required
def upload_query():
    """
    This is a flask function for the backend logic
    to upload a csv file to the database.
    """

    if request.method == "GET":
        return render_template("ops/upload_query.html", **db.get_info())

    tag_query = {
        "exact": [False],
        "nlp_apply": [False],
        "include": [None],
        "exclude": [None]
    }

    search_query = request.form.get("regex_query")
    use_negation = False # bool(request.form.get("view_negations"))
    hide_duplicates = False # not bool(request.form.get("keep_duplicates"))
    skip_after_event = False # bool(request.form.get("skip_after_event"))


    db.save_query(search_query, use_negation,
                    hide_duplicates, skip_after_event, tag_query)

    db.empty_annotations()

    #TODO: use flask executor to run this in the background
    nlp_processor = NLP_processor.NlpProcessor()
    nlp_processor.automatic_nlp_processor()

    if "annotation_ids" in session:
        session.pop("annotation_ids")
    if "annotation_number" in session:
        session.pop("annotation_number")
    if "patient_id" in session:
        session.pop("patient_id")
    return redirect(url_for("ops.adjudicate_records"))


def _get_current_annotation_id():
    return session["annotation_ids"][session["annotation_number"]]


@bp.route("/save_adjudications", methods=["GET", "POST"])
@login_required
def save_adjudications():
    """
    Handle logic for the save_adjudications route.
    Used to edit and review annotations.
    """
    current_annotation_id = _get_current_annotation_id()

    def _update_annotation_date():
        new_date = request.form['date_entry']
        print(new_date)
        db.update_annotation_date(current_annotation_id, new_date)

    def _delete_annotation_date():
        db.delete_annotation_date(current_annotation_id)

    def _add_annotation_comment():
        db.add_annotation_comment(current_annotation_id, request.form['comment'])

    def _move_to_previous_annotation():
        if session["annotation_number"] > 0:
            session["annotation_number"] -= 1
            session.modified = True

    def _move_to_next_annotation():
        if session["annotation_number"] < (len(session["annotation_ids"]) - 1):
            session["annotation_number"] += 1
            session.modified = True

    def _adjudicate_annotation():
        db.mark_annotation_reviewed(current_annotation_id)
        session["annotation_ids"].pop(session["annotation_number"])
        session.modified = True

    actions = {
        'new_date': _update_annotation_date,
        'del_date': _delete_annotation_date,
        'comment': _add_annotation_comment,
        'prev': _move_to_previous_annotation,
        'next': _move_to_next_annotation,
        'adjudicate': _adjudicate_annotation
    }

    action = request.form['submit_button']
    if action in actions:
        actions[action]()

    return redirect(url_for("ops.adjudicate_records"))


@bp.route("/adjudicate_records", methods=["GET", "POST"])
@login_required
def adjudicate_records():
    """
    Serve the 'adjudicate_records' page.
    Handle the logic associated with the main CEDARS page.
    """
    pt_id = None
    if request.method == "POST":
        if request.form["patient_id"]:
            pt_id = int(request.form["patient_id"])
            print("Search patient: ", pt_id)

    _initialize_session(pt_id)

    if len(session['annotation_ids']) == 0:
        _prepare_for_next_patient()
        if not session["patient_id"]:
            return render_template("ops/annotations_complete.html", **db.get_info())

    if len(session['annotation_ids']) == 0:
        _prepare_for_next_patient()
        return redirect(url_for("ops.adjudicate_records"))

    current_annotation_id = session["annotation_ids"][session["annotation_number"]]

    annotation = db.get_annotation(current_annotation_id)
    note = db.get_annotation_note(current_annotation_id)

    context = {
        'name': current_user.username,
        'event_date': _format_date(annotation.get('event_date')),
        'note_date': _format_date(note['text_date']),
        'pre_token_sentence': annotation['sentence'][:annotation['start_index']],
        'token_word': annotation['sentence'][annotation['start_index']:annotation['end_index']],
        'post_token_sentence': annotation['sentence'][annotation['end_index']:],
        'pos_start': session["annotation_number"] + 1,
        'total_pos': len(session["annotation_ids"]),
        'patient_id': session['patient_id'],
        'comments': annotation["comments"],
        'full_note': note['text'],
        'isLocked': session.get("hasBeenLocked", False),
        **db.get_info()
    }

    session["hasBeenLocked"] = False

    return render_template("ops/adjudicate_records.html", **context)

def _initialize_session(pt_id=None):
    if "patient_id" not in session and not pt_id:
        pt_id = db.get_patient()
    session.update({
        "patient_id": pt_id,
        "annotation_number": 0,
        "annotation_ids": db.get_patient_annotation_ids(pt_id)
    })
    session.modified = True

def _prepare_for_next_patient():
    db.mark_patient_reviewed(session['patient_id'])
    session.pop("patient_id")
    session.modified = True
    _initialize_session()


def _format_date(date_obj):
    if date_obj:
        return str(date_obj.date())
    return "None"


@bp.route('/download_annotations')
@admin_required
def download_file ():
    """
    This is a flask function for the backend logic
                    for the download_annotations route.
    It will create a csv file of the current annotations and send it to the user.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    data = db.get_all_annotations()
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], "annotations.csv")
    annotations = pd.DataFrame(data)
    annotations.to_csv(file_path)

    return send_file(file_path, as_attachment=True)
