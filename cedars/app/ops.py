"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import os
import re
from datetime import datetime, timezone

import pandas as pd
import flask
from dotenv import dotenv_values
from flask import (
    Blueprint, render_template,
    redirect, session, request,
    url_for, flash, g
)

from loguru import logger
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from rq import Retry, Callback
from rq.registry import FailedJobRegistry, FinishedJobRegistry
from . import db
from . import nlpprocessor
from . import auth
from .database import minio

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


def convert_to_int(value):
    """Convert to integer if possible, otherwise return the string."""
    try:
        return int(value)
    except ValueError:
        return value


@bp.route("/project_details", methods=["GET", "POST"])
@auth.admin_required
def project_details():
    """
    This is a flask function for the backend logic for the proj_details route.
    It is used by the admin to view and alter details of the current project.
    """

    if request.method == "POST":
        if "update_project_name" in request.form:
            project_name = request.form.get("project_name").strip()
            old_name = db.get_proj_name()
            if old_name is None:
                if len(project_name) > 0:
                    db.create_project(project_name, current_user.username)
                    flash(f"Project **{project_name}** created.")
            else:
                if len(project_name) > 0:
                    db.update_project_name(project_name)
                    flash(f"Project name updated to {project_name}.")
            return render_template("index.html", **db.get_info())

        if "terminate" in request.form:
            terminate_clause = request.form.get("terminate_conf")
            if len(terminate_clause.strip()) > 0:
                if terminate_clause == 'DELETE EVERYTHING':
                    db.terminate_project()
                    # reset all rq queues
                    flask.current_app.task_queue.empty()
                    auth.logout_user()
                    session.clear()
                    flash("Project Terminated.")
                    return render_template("index.html", **db.get_info())
            else:
                flash("Termination failed.. Please enter 'DELETE EVERYTHING' in confirmation")

    return render_template("ops/project_details.html",
                           tasks=db.get_tasks_in_progress(), **db.get_info())


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
        'csv': pd.read_csv, # nrows = 1
        'xlsx': pd.read_excel, # nrows = 1
        'json': pd.read_json, # lines = True, nrows = 1
        'parquet': pd.read_parquet,
        'pickle': pd.read_pickle, # 
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
        obj = minio.get_object(g.bucket_name, filepath)

        # Read one line of the file to conserve memory and computation
        if extension in ['csv', 'xlsx']:
            data_frame_line_1 = loaders[extension](obj, nrows = 1)
        elif extension == 'json':
            data_frame_line_1 = loaders[extension](obj, lines = True, nrows = 1)
        else:
            # TODO
            # Add generator to load a single line from other file types
            data_frame_line_1 = loaders[extension](obj)

        required_columns = ['patient_id', 'text_id', 'text', 'text_date']

        for column in required_columns:
            if column not in data_frame_line_1.columns:
                flash(f"Column {column} missing from uploaded file.")
                flash("Failed to save file to database.")
                raise RuntimeError(f"Uploaded file does not contain column '{column}'.")

        # Re-initialise object from minio to load it again
        obj = minio.get_object(g.bucket_name, filepath)
        data_frame = loaders[extension](obj)
        return data_frame

    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File '{filepath}' not found.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to load the file '{filepath}' due to: {str(exc)}") from exc


# Pylint disabled due to naming convention.
def EMR_to_mongodb(filepath):  # pylint: disable=C0103
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
        if i+1 % 100 == 0:
            logger.info(f"Documents uploaded for patient #{i+1}")

    db.create_index("PATIENTS", [("patient_id", {"unique": True})])
    db.create_index("NOTES", ["patient_id",
                              ("text_id", {"unique": True})])
    logger.info("Completed document migration to mongodb database.")


@bp.route("/upload_data", methods=["GET", "POST"])
@auth.admin_required
def upload_data():
    """
    This is a flask function for the backend logic to upload a file to the database.
    """
    filename = None
    if request.method == "POST":
        # if db.get_task(f"upload_and_process:{current_user.username}"):
        #     flash("A file is already being processed.")
        #     return redirect(request.url)
        minio_file = request.form.get("miniofile")
        if minio_file != "None" and minio_file is not None:
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
                flash("""Invalid file type.
                      Please upload a .csv, .xlsx, .json, .parquet, .pickle, .pkl, or .xml file.""")
                return redirect(request.url)

            filename = f"uploaded_files/{secure_filename(file.filename)}"
            size = os.fstat(file.fileno()).st_size

            try:
                minio.put_object(g.bucket_name,
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
        files = [(obj.object_name, obj.size)
                 for obj in minio.list_objects(g.bucket_name,
                                               prefix="uploaded_files/")]
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
        current_query = db.get_search_query()
        return render_template("ops/upload_query.html",
                               current_query=current_query,
                               **db.get_info(),
                               **db.get_search_query_details())

    tag_query = {
        "exact": False,
        "nlp_apply": bool(request.form.get("nlp_apply"))
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

    use_negation = False  # bool(request.form.get("view_negations"))
    hide_duplicates = not bool(request.form.get("keep_duplicates"))
    skip_after_event = bool(request.form.get("skip_after_event"))

    new_query_added = db.save_query(search_query, use_negation,
                                    hide_duplicates, skip_after_event, tag_query)

    # TODO: add a javascript confirm box to make sure the user wants to update the query
    if new_query_added:
        db.empty_annotations()
        db.reset_patient_reviewed()

    if "patient_id" in session:
        session.pop("patient_id")
        session.modified = True

    do_nlp_processing()
    return redirect(url_for("stats_page.stats_route"))


@bp.route("/start_process")
def do_nlp_processing():
    """
    Run NLP workers
    TODO: requeue failed jobs
    """
    nlp_processor = nlpprocessor.NlpProcessor()
    pt_ids = db.get_patient_ids()
    # add task to the queue
    for patient in pt_ids:
        flask.current_app.task_queue.enqueue(
            nlp_processor.automatic_nlp_processor,
            args=(patient,),
            job_id=f'spacy:{patient}',
            description=f"Processing patient {patient} with spacy",
            retry=Retry(max=3),
            on_success=Callback(db.report_success),
            on_failure=Callback(db.report_failure),
            kwargs={
                "user": current_user.username,
                "job_id": f'spacy:{patient}',
                "description": f"Processing patient {patient} with spacy"
            }
        )
    return redirect(url_for("ops.get_job_status"))


@bp.route("/job_status", methods=["GET"])
def get_job_status():
    """
    Directs the user to the job status page.
    """
    return render_template("ops/job_status.html",
                           tasks=db.get_tasks_in_progress(), **db.get_info())


@bp.route('/queue_stats', methods=['GET'])
def queue_stats():
    """
    Returns details of how many jobs are left in the queue and the status of
    completed jobs. Is used for the project statistics page.
    """
    queue_length = len(flask.current_app.task_queue)
    failed_job_registry = FailedJobRegistry(queue=flask.current_app.task_queue)
    failed_jobs = len(failed_job_registry)
    finished_job_registry = FinishedJobRegistry(queue=flask.current_app.task_queue)
    successful_jobs = len(finished_job_registry)
    return flask.jsonify({'queue_length': queue_length,
                          'failed_jobs': failed_jobs,
                          'successful_jobs': successful_jobs
                          })


@bp.route("/save_adjudications", methods=["GET", "POST"])
@login_required
def save_adjudications():
    """
    Handle logic for the save_adjudications route.
    Used to edit and review annotations.
    """
    current_annotation_id = session["annotations"][session["index"]]

    def _update_annotation_date():
        new_date = request.form['date_entry']
        logger.info(f"Updating {current_annotation_id}: {new_date}")
        db.update_annotation_date(current_annotation_id, new_date)
        _adjudicate_annotation(updated_date = True)


    def _delete_annotation_date():
        skip_after_event = db.get_search_query(query_key="skip_after_event")
        db.delete_annotation_date(current_annotation_id)

    def _move_to_previous_annotation():
        if session["index"] > 0:
            session["index"] -= 1
            session.modified = True

    def _move_to_next_annotation():
        if session["index"] < session["total_count"] - 1:
            session["index"] += 1
            session.modified = True

    def _adjudicate_annotation(updated_date = False):
        skip_after_event = db.get_search_query(query_key="skip_after_event")
        if session["unreviewed_annotations_index"][session["index"]] == 1:
            db.mark_annotation_reviewed(current_annotation_id)
            if updated_date and skip_after_event:
                session["unreviewed_annotations_index"] = [0] * len(session["unreviewed_annotations_index"])

            session["unreviewed_annotations_index"][session["index"]] = 0
            session.modified = True
            # if one annotation has the event date, mark the patient
            # as reviewed because we don't need to review the rest
            # this could be based on a parameter though
            # TODO: add logic based on tags if we need to keep reviewing
            if len(db.get_patient_annotation_ids(session["patient_id"])) == 0:
                db.mark_patient_reviewed(session["patient_id"],
                                         reviewed_by=current_user.username)
                db.set_patient_lock_status(session["patient_id"], False)
                session.pop("patient_id")
            elif db.get_annotation_date(current_annotation_id) is not None:
                db.mark_note_reviewed(db.get_annotation(current_annotation_id)["note_id"],
                                      reviewed_by=current_user.username)
                db.mark_patient_reviewed(session["patient_id"],
                                         reviewed_by=current_user.username)
                if db.get_search_query(query_key="skip_after_event"):
                    db.set_patient_lock_status(session["patient_id"], False)
                    session.pop("patient_id")
            else:
                session["index"] = session["unreviewed_annotations_index"].index(1)
        elif 1 in session["unreviewed_annotations_index"]:
            # any unreviewed annotations left?
            session["index"] = session["unreviewed_annotations_index"].index(1)
        else:
            flash("Annotation already reviewed.")
            if session["index"] < session["total_count"] - 1:
                session["index"] += 1

        session.modified = True

    def _add_annotation_comment():
        db.add_comment(current_annotation_id, request.form['comment'])



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
    _add_annotation_comment()

    # the session has been cleared so get the next patient
    if session.get("patient_id") is None:
        return redirect(url_for("ops.adjudicate_records"))

    return redirect(url_for("ops.show_annotation"))


@bp.route("/show_annotation", methods=["GET"])
def show_annotation():
    """
    Formats and displays the current annotation being viewed by the user.
    """
    index = session.get("index", 0)
    annotation = db.get_annotation(session["annotations"][index])
    note = db.get_annotation_note(str(annotation["_id"]))
    if not note:
        flash("Annotation note not found.")
        return redirect(url_for("ops.adjudicate_records"))

    annotation_data = {
        "pos_start": index + 1,
        "total_pos": session["total_count"],
        "patient_id": session["patient_id"],
        "name": current_user.username,
        "note_date": _format_date(annotation.get('text_date')),
        "event_date": _format_date(db.get_event_date(session["patient_id"])),
        "note_comment": db.get_patient_by_id(session["patient_id"])["comments"],
        "highlighted_sentence" : get_highlighted_sentence(annotation, note),
        "note_id": annotation["note_id"],
        "full_note": highlighted_text(note),
        "tags": [note.get("text_tag_1", ""),
                 note.get("text_tag_2", ""),
                 note.get("text_tag_3", ""),
                 note.get("text_tag_4", ""),
                 note.get("text_tag_5", "")]
    }

    return render_template("ops/adjudicate_records.html",
                           **annotation_data,
                           **db.get_info())


@bp.route("/adjudicate_records", methods=["GET", "POST"])
@login_required
def adjudicate_records():
    """
    Adjudication Workflow:

    ### Get the next available patient

    1. The first time this page is hit, get a patient who is not reviewed from the database
    2. Since the patient is not reviewed in the db,
                            they should have annotations, if not, skip to the next patientd

    ### Search for a patient

    1. If the user searches for a patient, get the patient from the database
    2. If the patient has no annotations, skip to the next patient

    ### show the annotation
    3. Get the first annotation and show it to the user
    4. User can adjudicate the annotation or browse back and forth
    5. If the annotation has an event date, mark the note as reviewed
        5.a. If the note has been reviewed, mark the note as reviewed
        5.b. If the all notes have been reviewed, mark the patient as reviewed
    6. If the annotation has no event date, show the next annotation
    7. If there are no more annotations to be reviewed, mark the patient as reviewed
    8. All annotations are a mongodb document.

    """

    patient_id = None
    if request.method == "GET":
        if session.get("patient_id") is not None:
            logger.info(f"Getting patient: {session.get('patient_id')} from session")
            return redirect(url_for("ops.show_annotation"))
        patient_id = db.get_patients_to_annotate()
    else:
        session.pop("patient_id", None)
        search_patient = request.form.get("patient_id")
        if search_patient and len(search_patient.strip()) > 0:
            search_patient = convert_to_int(search_patient)
            patient = db.get_patient_by_id(search_patient)
            if patient:
                patient_id = patient["patient_id"]

        if patient_id is None:
            # if the search return no patient, get the next patient
            flash(f"Patient {search_patient} does not exist. Showing next patient")
            patient_id = db.get_patients_to_annotate()

    if patient_id is None:
        return render_template("ops/annotations_complete.html", **db.get_info())

    res = db.get_all_annotations_for_patient(patient_id)

    annotations = res["annotations"]
    total_count = res["total"]
    all_annotation_index = res["all_annotation_index"]
    unreviewed_annotations_index = res["unreviewed_annotations_index"]

    if total_count == 0:
        logger.info(f"Patient {patient_id} has no annotations. Showing next patient")
        flash(f"Patient {patient_id} has no annotations. Showing next patient")
        return redirect(url_for("ops.adjudicate_records"))
    elif unreviewed_annotations_index.count(1) == 0:
        flash(f"Patient {patient_id} has no annotations left review. Showing all annotations.")
        session["patient_id"] = patient_id
        session["total_count"] = total_count
        session["annotations"] = annotations
        session["all_annotation_index"] = all_annotation_index
        session["unreviewed_annotations_index"] = unreviewed_annotations_index
        # in case of reviewed patient show everything..
        session["index"] = 0
    else:
        logger.info(f"Total annotations for patient {patient_id}: {total_count}")
        session["patient_id"] = patient_id
        session["total_count"] = total_count
        session["annotations"] = annotations
        session["all_annotation_index"] = all_annotation_index
        session["unreviewed_annotations_index"] = unreviewed_annotations_index
        session["index"] = all_annotation_index[unreviewed_annotations_index.index(1)]

    # db.set_patient_lock_status(patient_id, True)
    session.modified = True
    return redirect(url_for("ops.show_annotation"))


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
        highlighted_note.append(f'<b><mark>{text[start_index:end_index]}</mark></b>')
        prev_end_index = end_index

    highlighted_note.append(text[prev_end_index:])
    logger.info(highlighted_note)
    return " ".join(highlighted_note).replace("\n", "<br>")

def get_highlighted_sentence(annotation, note):
    """
    Returns highlighted text for a sentence in a note.
    """
    highlighted_note = []
    text = note["text"]

    

    sentence_start = annotation["sentence_start"]
    sentence_end = annotation["sentence_end"]
    if sentence_start == 0:
        prev_end_index = sentence_start
    else:
        # Padding to the left to ensure that all characters are caught
        prev_end_index = sentence_start - 1

    annotations = db.get_all_annotations_for_sentence(note["text_id"],
                                                      annotation["sentence_number"])
    logger.info(annotations)

    for annotation in annotations:
        start_index = annotation['note_start_index']
        end_index = annotation['note_end_index']
        # Make sure the annotations don't overlap
        if start_index < prev_end_index:
            continue

        highlighted_note.append(text[prev_end_index:start_index])
        highlighted_note.append(f'<b><mark>{text[start_index:end_index]}</mark></b>')
        prev_end_index = end_index

    highlighted_note.append(text[prev_end_index:sentence_end])
    logger.info(highlighted_note)
    return " ".join(highlighted_note).replace("\n", "<br>")

def _format_date(date_obj):
    res = None
    if date_obj:
        res = date_obj.date()
    return res


@bp.route('/download_page')
@bp.route('/download_page/<job_id>')
@auth.admin_required
def download_page(job_id=None):
    """
    Loads the page where an admin can download the results
    of annotations made for that project.
    """
    files = [(obj.object_name.rsplit("/", 1)[-1],
              obj.size,
              (
                  datetime.now(timezone.utc) - obj.last_modified).seconds//60
              ) for obj in minio.list_objects(
                   g.bucket_name,
                   prefix="annotated_files/")]

    if job_id is not None:
        return flask.jsonify({"files": files}), 202
    return render_template('ops/download.html', job_id=job_id, files=files, **db.get_info())


@bp.route('/download_annotations', methods=["POST"])
@auth.admin_required
def download_file(filename='annotations.csv'):
    """
    ##### Download Completed Annotations

    This generates a CSV file with the following specifications:
    1. Find all patients in the PATIENTS database,
            these patients become a single row in the CSV file.
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
    filename = request.form.get("filename")
    file = minio.get_object(g.bucket_name, f"annotated_files/{filename}")
    logger.info(f"Downloaded annotations from s3: {filename}")
    return flask.Response(
        file.stream(32*1024),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename=cedars_{filename}"}
    )


@bp.route('/create_download_task', methods=["GET"])
@auth.admin_required
def create_download():
    """
    Create a download task for annotations
    """
    job = flask.current_app.ops_queue.enqueue(
        db.download_annotations, "annotations.csv",
    )
    return flask.jsonify({'job_id': job.get_id()}), 202


@bp.route('/create_download_task_full', methods=["GET"])
@auth.admin_required
def create_download_full():
    """
    Create a download task for annotations
    """
    job = flask.current_app.ops_queue.enqueue(
        db.download_annotations, "annotations_full.csv", True
    )
    return flask.jsonify({'job_id': job.get_id()}), 202


@bp.route('/check_job/<job_id>')
@auth.admin_required
def check_job(job_id):
    """
    Returns the status of a job to the frontend.
    """
    logger.info(f"Checking job {job_id}")
    job = flask.current_app.ops_queue.fetch_job(job_id)
    if job.is_finished:
        return flask.jsonify({'status': 'finished', 'result': job.result}), 200
    elif job.is_failed:
        return flask.jsonify({'status': 'failed', 'error': str(job.exc_info)}), 500
    else:
        return flask.jsonify({'status': 'in_progress'}), 202
