"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import os
import re
from pathlib import Path
from io import BytesIO
import pandas as pd
from dotenv import dotenv_values
from flask import (
    Blueprint, render_template, send_file,
    redirect, session, request, url_for, flash,
    current_app
)
from loguru import logger
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from . import db
from . import nlpprocessor
from . import auth
from .database import client, mongo

logger.enable(__name__)

bp = Blueprint("ops", __name__, url_prefix="/ops")
config = dotenv_values(".env")


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
@auth.admin_required
def project_details():
    """
    This is a flask function for the backend logic for the proj_details route.
    It is used by the admin to view and alter details of the current project.
    """

    if request.method == "POST":
        project_name = request.form.get("project_name")
        if len(project_name.strip()) > 0:
            db.update_project_name(project_name)
            flash(f"Project name updated to {project_name}.")

        if "project_logo" in request.files:
            file = request.files["project_logo"]
            if allowed_image_file(secure_filename(file.filename)):
                file.save(Path(current_app.config["UPLOAD_FOLDER"]) / "project_logo.png")
                flash("Logo updated successfully.")
            else:
                flash("Invalid file type. Please upload a .png, .jpg, or .jpeg file.")

        return render_template("index.html", **db.get_info())

    return render_template("ops/project_details.html", **db.get_info())


def load_pandas_dataframe(filepath):
    """
    Load tabular data from a file into a pandas DataFrame.

    Args:
        filepath (str): The path to the file to load data from.
            Supported file extensions: csv, xlsx, json, parquet, pickle, pkl, xml.

    Returns:
        pd.DataFrame: DataFrame with the data from the file.

    Raises:
        ValueError: If the file extension is not supported.
        FileNotFoundError: If the file does not exist.
    """
    if not filepath:
        raise ValueError("Filepath must be provided.")

    extension = str(filepath).rsplit('.', maxsplit=1)[-1].lower()
    loaders = {
        'csv': pd.read_csv,
        'xlsx': pd.read_excel,
        'json': pd.read_json,
        'parquet': pd.read_parquet,
        'pickle': pd.read_pickle,
        'pkl': pd.read_pickle,
        'xml': pd.read_xml
    }

    if extension not in loaders:
        raise ValueError(f"""
                         Unsupported file extension '{extension}'. 
                         Supported extensions are 
                         {', '.join(loaders.keys())}.""")

    try:
        logger.info(filepath)
        obj = client.get_object("cedars", filepath)
        return loaders[extension](obj)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File '{filepath}' not found.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to load the file '{filepath}' due to: {str(exc)}") from exc


# Pylint disabled due to naming convention.
def EMR_to_mongodb(filepath): #pylint: disable=C0103
    """
    This function is used to open a csv file and load it's contents into the mongodb database.

    Args:
        filename (str) : The path to the file to load data from.
        For valid file extensions refer to the allowed_data_file function above.
    Returns:
        None
    """

    data_frame = load_pandas_dataframe(filepath)
    if data_frame is None:
        return

    logger.info(f"columns in dataframe:\n {data_frame.columns}")
    logger.debug(data_frame.head())
    id_list = data_frame["patient_id"].unique()
    logger.info("Starting document migration to mongodb database.")
    for i, p_id in enumerate(id_list):
        documents = data_frame[data_frame["patient_id"] == p_id]
        db.upload_notes(documents)

        logger.info(f"Documents uploaded for patient #{i+1}")

    logger.info("Completed document migration to mongodb database.")


@bp.route("/upload_data", methods=["GET", "POST"])
@auth.admin_required
def upload_data():
    """
    This is a flask function for the backend logic to upload a file to the database.
    """

    filename = None
    if request.method == "POST":
        filename = None
        minio_file = request.form.get("miniofile")
        if minio_file != "None":
            logger.info(f"Using minio file: {minio_file}")
            filename = minio_file
        else:
            if 'data_file' not in request.files:
                flash('No file part')
                return redirect(request.url)

            file = request.files['data_file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            if file and not allowed_data_file(file.filename):
                flash("Invalid file type. Please upload a .csv, .xlsx, .json, .parquet, .pickle, .pkl, or .xml file.")
                return redirect(request.url)
            
            filename = f"uploaded_files/{secure_filename(file.filename)}"
            size = os.fstat(file.fileno()).st_size
            try:
                client.put_object("cedars",
                                filename,
                                file,
                                size)
                logger.info(f"File - {file.filename} uploaded successfully.")
                flash(f"{filename} uploaded successfully.")

            except Exception as e:
                filename = None
                flash(f"Failed to upload file: {str(e)}")
                return redirect(request.url)
        if filename:
            try:
                EMR_to_mongodb(filename)
                flash(f"Data from {filename} uploaded to the database.")
                return redirect(url_for('ops.upload_query'))
            except Exception as e:
                flash(f"Failed to upload data: {str(e)}")
                return redirect(request.url)
    try:
        files = [(obj.object_name, obj.size) for obj in client.list_objects("cedars", prefix="uploaded_files/")]
    except Exception as e:
        flash(f"Error listing files: {e}")
        files = []
    
    return render_template("ops/upload_file.html", files=files, **db.get_info())
    

@bp.route("/upload_query", methods=["GET", "POST"])
@auth.admin_required
def upload_query():
    """
    This is a flask function for the backend logic
    to upload a csv file to the database.
    """
    # TODO: make regex translation using chatGPT if API is available

    if request.method == "GET":
        return render_template("ops/upload_query.html", **db.get_info())

    tag_query = {
        "exact": [False],
        "nlp_apply": [False],
        "include": [None],
        "exclude": [None]
    }

    search_query = request.form.get("regex_query")
    search_query_pattern = (
        r'^\s*('
        r'(\(\s*[a-zA-Z0-9*?]+(\s*AND\s*[a-zA-Z0-9*?]+)*\s*\))|'
        r'[a-zA-Z0-9*?]+)'
        r'('
        r'\s*OR\s+'
        r'((\(\s*[a-zA-Z0-9*?]+(\s*AND\s*[a-zA-Z0-9*?]+)*\s*\))|'
        r'[a-zA-Z0-9*?]+))*'
        r'\s*$'
    )
    try:
        re.match(search_query, search_query_pattern)
    except re.error:
        flash("Invalid query.")
        return render_template("ops/upload_query.html", **db.get_info())

    use_negation = False # bool(request.form.get("view_negations"))
    hide_duplicates = False # not bool(request.form.get("keep_duplicates"))
    skip_after_event = False # bool(request.form.get("skip_after_event"))

    db.save_query(search_query, use_negation,
                    hide_duplicates, skip_after_event, tag_query)

    db.empty_annotations()
    db.reset_patient_reviewed()

    #TODO: use flask executor to run this in the background
    nlp_processor = nlpprocessor.NlpProcessor()

    for patient in db.get_all_patients():
        nlp_processor.automatic_nlp_processor(patient["patient_id"])

    # remove session variables
    if "annotation_ids" in session:
        session.pop("annotation_ids")
        session.modified = True
    if "annotation_number" in session:
        session.pop("annotation_number")
        session.modified = True
    if "patient_id" in session:
        session.pop("patient_id")
        session.modified = True
    return redirect(url_for("ops.adjudicate_records"))


def _get_current_annotation_id():
    return session["annotation_ids"][session["annotation_number"]]

@bp.route("/terminate", methods=["GET"])
@auth.admin_required
def terminate():
    """
    This is a flask function for the backend logic to terminate the project.
    """
    session.clear()
    db.terminate_project()
    flash('Database reset successfully.', 'success')
    return redirect(url_for("auth.register"))

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
        logger.info(f"Updating {current_annotation_id}: {new_date}")
        db.update_annotation_date(current_annotation_id, new_date)
        _adjudicate_annotation()

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
        # if one annotation has the event date, mark the patient
        # as reviewed because we don't need to review the rest
        # this could be based on a parameter though
        # TODO: add logic based on tags if we need to keep reviewing
        if db.get_annotation_date(current_annotation_id) is not None:
            db.mark_patient_reviewed(session["patient_id"], reviewed_by=current_user.username)
            session.pop("patient_id")
        session["annotation_ids"].pop(session["annotation_number"])
        if session["annotation_number"] >= len(session["annotation_ids"]):
            session["annotation_number"] -= 1
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
            try:
                pt_id = int(request.form["patient_id"])
            except ValueError:
                flash("Patient ID must be an integer.")
                return redirect(url_for("ops.adjudicate_records"))
            
            patient_info = db.get_patient(pt_id)
            if patient_info is None:
                flash(f"Patient {pt_id} does not exist.")
                return redirect(url_for("ops.adjudicate_records"))
            elif patient_info["reviewed"]:
                flash(f"Patient {pt_id} has no annotations.")
                return redirect(url_for("ops.adjudicate_records"))
            logger.info(f"Search patient: {pt_id}")

    _initialize_session(pt_id)
    if "patient_id" not in session:
        return render_template("ops/annotations_complete.html", **db.get_info())
    
    logger.debug(session)
    while len(session["annotation_ids"]) == 0:
        _prepare_for_next_patient()
        if "patient_id" not in session:
            return render_template("ops/annotations_complete.html", **db.get_info())
        
    current_annotation_id = session["annotation_ids"][session["annotation_number"]]
    logger.debug(f"Current annotation id: {current_annotation_id}")
    annotation = db.get_annotation(current_annotation_id)
    logger.debug(f"Current annotation: {annotation}")
    note = db.get_annotation_note(current_annotation_id)
    logger.debug(f"Current note: {note}")

    context = {
        'name': current_user.username,
        'event_date': _format_date(annotation.get('event_date')),
        'note_date': _format_date(annotation.get('text_date')),
        'note_id': note["text_id"],
        'pre_token_sentence': re.sub(r'\n+|\r\n', '\n', annotation['sentence'][:annotation['start_index']]).strip(),
        'token_word': annotation['sentence'][annotation['start_index']:annotation['end_index']],
        'post_token_sentence': re.sub(r'\n+|\r\n', '\n', annotation['sentence'][annotation['end_index']:]).strip(),
        'pos_start': session["annotation_number"] + 1,
        'total_pos': len(session["annotation_ids"]),
        'patient_id': session['patient_id'],
        'comments': annotation["comments"],
        'full_note': highlighted_text(note),
        'tags': [note.get("text_tag_1",""), note.get("text_tag_2", ""), note.get("text_tag_3", ""), note.get("text_tag_4", "")],
        'isLocked': session.get("hasBeenLocked", False),
        **db.get_info()
    }

    session["hasBeenLocked"] = False

    return render_template("ops/adjudicate_records.html", **context)


def highlighted_text(note):
    """
    Returns highlighted text for a note.
    """
    highlighted_note = []
    prev_end_index = 0
    text = note["text"]

    annotations = db.get_all_annotations_for_note(note["text_id"])
    logger.info(annotations)

    for annotation in annotations:
        start_index = annotation['note_start_index']
        end_index = annotation['note_end_index']
        # Make sure the annotations don't overlap
        if start_index < prev_end_index:
            continue
        
        highlighted_note.append(text[prev_end_index:start_index])
        highlighted_note.append(f'<mark>{text[start_index:end_index]}</mark>')
        prev_end_index = end_index

    highlighted_note.append(text[prev_end_index:])
    logger.info(highlighted_note[1])
    return " ".join(highlighted_note).replace("\n", "<br>")

def _initialize_session(pt_id=None):
    if pt_id is not None or "patient_id" not in session:
        pt_id = pt_id if pt_id else db.get_patient_to_annotate()
        if pt_id is not None:
            # found a patient with unreviewed notes
            session.update({
                "patient_id": pt_id,
                "annotation_number": 0,
                "annotation_ids": db.get_patient_annotation_ids(pt_id)
            })
        session.modified = True

def _prepare_for_next_patient():
    logger.info(f"Marking patient: {session['patient_id']} as reviewed")
    db.mark_patient_reviewed(session['patient_id'],
                             reviewed_by=current_user.username)
    session.pop("patient_id")
    _initialize_session()


def _format_date(date_obj):
    if date_obj:
        return str(date_obj.date())
    return "None"


@bp.route('/download_annotations')
@auth.admin_required
def download_file (filename = 'annotations.csv'):
    """
    ##### Download Completed Annotations

    This generates a CSV file with the following specifications:
    1. Find all patients in the PATIENTS database, these patients become a single row in the CSV file.
    2. For each patient -
        a. list the number of total notes in the database
        b. list the number of reviewed notes
        c. list the number of total sentences from annotations
        d. list the number of reviewed sentences
        e. list all sentences as a list of strings
        f. add event date from the annotations for each patient
        g. add the first and last note date for each patient
    3. Convert all columns to proper datatypes
    """
    logger.info("Downloading annotations")
    patients = db.get_all_patients()
    data = []
    for patient in patients:
        patient_id = patient["patient_id"]
        notes = db.get_patient_notes(patient_id, check_reviewed = False)
        reviewed_notes = db.get_patient_notes(patient_id, reviewed=True)
        reviewed_sentences = db.get_patient_annotation_ids(patient_id, reviewed=True,  key="sentence")
        unreviewed_sentences = db.get_patient_annotation_ids(patient_id, reviewed=False,  key="sentence")
        sentences = reviewed_sentences + unreviewed_sentences
        total_sentences = len(sentences)
        event_date = db.get_event_date(patient_id)
        first_note_date = db.get_first_note_date_for_patient(patient_id)
        last_note_date = db.get_last_note_date_for_patient(patient_id)
        data.append([patient_id, len(notes), len(reviewed_notes),
                     total_sentences, len(reviewed_sentences), reviewed_sentences,
                     event_date, first_note_date, last_note_date])
  
    df = pd.DataFrame(data, columns=["patient_id", "total_notes", "reviewed_notes", "total_sentences", "reviewed_sentences", "sentences", "event_date", "first_note_date", "last_note_date"])
    data_bytes = df.to_csv().encode('utf-8')
    csv_buffer = BytesIO(data_bytes)
    client.put_object("cedars",
                      f"annotated_files/{filename}",
                      data=csv_buffer,
                      length=len(data_bytes),
                      content_type="application/csv")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    client.fget_object("cedars", filename, file_path)
    logger.info(f"File saved to {file_path}")
    return send_file(file_path, as_attachment=True)
