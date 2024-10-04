"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import os
import re
from datetime import datetime, timezone
import tempfile
import pandas as pd
import pyarrow.parquet as pq
import flask
from dotenv import dotenv_values
from flask import (
    Blueprint, render_template,
    redirect, session, request,
    url_for, flash, g, jsonify
)

from loguru import logger
import requests
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from rq import Retry, Callback
from rq.registry import FailedJobRegistry
from rq.registry import FinishedJobRegistry, StartedJobRegistry
from . import db
from . import nlpprocessor
from . import auth
from .database import minio
from .api import load_pines_url, kill_pines_api
from .api import get_token_status


bp = Blueprint("ops", __name__, url_prefix="/ops")
config = dotenv_values(".env")

logger.enable(__name__)


def allowed_data_file(filename):
    """
    This function is used to check if a file has a valid extension for us to load tabular data from.

    Args:
        filepath (str) : The path to the file.
    Returns:
        (bool) : True if the file is of a supported type.
    """
    allowed_extensions = {'csv', 'xlsx', 'json', 'parquet', 'pickle', 'pkl', 'xml', 'csv.gz'}

    for extension in allowed_extensions:
        if filename.endswith('.' + extension):
            return True

    return False


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
        if "update_project_name" in request.form:
            project_name = request.form.get("project_name").strip()
            old_name = db.get_proj_name()
            if old_name is None:
                project_id = os.getenv("PROJECT_ID", None)
                db.create_project(project_name, current_user.username,
                                    project_id = project_id)
                flash(f"Project **{project_name}** created.")
            else:
                project_info = db.get_info()
                project_id = project_info["project_id"]
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
                            **db.get_info())

def read_gz_csv(filename, *args, **kwargs):
    '''
    Function to read a GZIP compressed csv to a pandas DataFrame.
    '''
    return pd.read_csv(filename, compression='gzip', *args, **kwargs)


def load_pandas_dataframe(filepath, chunk_size=1000):
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
    # If the extension is gz, we can assume it is a csv.gz file as this
    # is the only filecheck supported in the allowed_data_file check
    loaders = {
        'csv': pd.read_csv,
        'xlsx': pd.read_excel,
        'json': pd.read_json,
        'parquet': pd.read_parquet,
        'pickle': pd.read_pickle,
        'pkl': pd.read_pickle,
        'xml': pd.read_xml,
        'gz' : read_gz_csv,
    }

    if extension not in loaders:
        raise ValueError(f"""
                         Unsupported file extension '{extension}'.
                         Supported extensions are
                         {', '.join(loaders.keys())}.""")

    try:
        logger.info(filepath)
        obj = minio.get_object(g.bucket_name, filepath)
        local_directory = tempfile.gettempdir()
        os.makedirs(local_directory, exist_ok=True)
        local_filename = os.path.join(local_directory, os.path.basename(filepath))
        minio.fget_object(g.bucket_name, filepath, local_filename)
        logger.info(f"File downloaded successfully to {local_filename}")

        # file_columns = []
        # # Read one line of the file to conserve memory and computation
        # if extension in ['csv', 'xlsx', 'gz']:
        #     data_frame_line_1 = loaders[extension](obj, nrows = 1)
        #     file_columns = data_frame_line_1.columns
        # elif extension == 'json':
        #     data_frame_line_1 = loaders[extension](obj, lines = True, nrows = 1)
        #     file_columns = data_frame_line_1.columns
        # elif extension == 'parquet':
        #     # For Parquet, we'll check columns using pyarrow
        #     parquet_file = pq.ParquetFile(obj)
        #     file_columns = parquet_file.schema.names
        # else:
        #     # TODO
        #     # Add generator to load a single line from other file types
        #     pass
        # required_columns = ['patient_id', 'text_id', 'text', 'text_date']

        # if len(file_columns) == 0:
        #     flash("Can't verify columns for the uploaded file (Only csv, csv.gz and xlsx supported)... Reading whole file")
        # else:
        #     missing_columns = []
        #     for column in required_columns:
        #         if column not in file_columns:
        #             missing_columns.append(column)
        #     if len(missing_columns) > 0:
        #         missing_columns_error = "\n".join(missing_columns)
        #         flash(f'Column {missing_columns_error} missing from uploaded file.')
        #         flash("Failed to save file to database.")
        #         raise RuntimeError(f"Uploaded file does not contain column '{missing_columns_error}'.")

        # obj = minio.get_object(g.bucket_name, filepath)
        # Re-initialise object from minio to load it again
        if extension == 'parquet':
            parquet_file = pq.ParquetFile(local_filename)
            for batch in parquet_file.iter_batches(batch_size=chunk_size):
                yield batch.to_pandas()
        else:
            chunks = loaders[extension](local_filename, chunksize=chunk_size)
            for chunk in chunks:
                yield chunk

    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File '{filepath}' not found.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to load the file '{filepath}' due to: {str(exc)}") from exc
    finally:
        obj.close()
        obj.release_conn()
        if 'local_filepath' in locals() and os.path.exists(local_filename):
            os.remove(local_filename)
            logger.info(f"Removed temporary file: {local_filename}")


def prepare_note(note_info):
    date_format = '%Y-%m-%d'
    note_info["text_date"] = datetime.strptime(note_info["text_date"], date_format)
    note_info["reviewed"] = False
    note_info["text_id"] = str(note_info["text_id"]).strip()
    note_info["patient_id"] = str(note_info["patient_id"]).strip()
    return note_info


def prepare_patients(patient_ids):
    return {str(p_id).strip() for p_id in patient_ids}


def EMR_to_mongodb(filepath, chunk_size=1000):
    """
    This function is used to open a file and load its contents into the MongoDB database in chunks.

    Args:
        filepath (str): The path to the file to load data from.
        chunk_size (int): Number of rows to process per chunk.

    Returns:
        None
    """
    logger.info("Starting document migration to MongoDB database.")

    total_rows = 0
    total_chunks = 0
    all_patient_ids = set()

    try:
        for chunk in load_pandas_dataframe(filepath, chunk_size):
            total_chunks += 1
            rows_in_chunk = len(chunk)
            total_rows += rows_in_chunk

            logger.info(f"Processing chunk {total_chunks} with {rows_in_chunk} rows")

            # Prepare notes
            notes_to_insert = [prepare_note(row.to_dict()) for _, row in chunk.iterrows()]

            # Collect patient IDs
            chunk_patient_ids = set(chunk['patient_id'])
            chunk_patient_ids = prepare_patients(chunk_patient_ids)
            all_patient_ids.update(chunk_patient_ids)

            # Bulk insert notes
            inserted_count = db.bulk_insert_notes(notes_to_insert)
            logger.info(f"Inserted {inserted_count} notes from chunk {total_chunks}")

        # Bulk upsert patients
        upserted_count = db.bulk_upsert_patients(all_patient_ids)
        logger.info(f"Upserted {upserted_count} patients")

        logger.info(f"Completed document migration to MongoDB database. "
                    f"Total rows processed: {total_rows}, "
                    f"Total chunks processed: {total_chunks}, "
                    f"Total unique patients: {len(all_patient_ids)}")

    except Exception as e:
        logger.error(f"An error occurred during document migration: {str(e)}")
        flash(f"Failed to upload data: {str(e)}")
        raise


# Pylint disabled due to naming convention.
# def EMR_to_mongodb(filepath, chunk_size=10000):  # pylint: disable=C0103
#     """
#     This function is used to open a csv file and load it's contents into the mongodb database.

#     Args:
#         filename (str) : The path to the file to load data from.
#         For valid file extensions refer to the allowed_data_file function above.
#     Returns:
#         None
#     """
#     for i, chunk in enumerate(load_pandas_dataframe(filepath, chunk_size)):
#         logger.info(f"Processing chunk {i+1}")
#         logger.debug(f"Columns in chunk:\n {chunk.columns}")
#         logger.debug(chunk.head())
#         db.upload_notes(chunk)

#     db.create_index("PATIENTS", [("patient_id", {"unique": True})])
#     db.create_index("NOTES", ["patient_id",
#                               ("text_id", {"unique": True})])
#     logger.info("Completed document migration to mongodb database.")


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
                                 size,
                                 part_size=10*1024*1024,
                                 num_parallel_uploads=10
                                 )
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

    use_pines = bool(request.form.get("nlp_apply"))
    superbio_api_token = session.get('superbio_api_token')
    if superbio_api_token is not None and use_pines:
        # If using a PINES server via superbio,
        # ensure that the current token works properly
        token_status = get_token_status(superbio_api_token)
        if token_status['has_expired'] is True:
            # If we are using a token, and this token has expired
            # then we cancell the process and do not add anything to the queue.
            logger.info('The current token has expired. Logging our user.')
            redirect(url_for('auth.logout'))
        elif token_status['is_valid'] is False:
            logger.error(f'Passed invalid token : {superbio_api_token}')
            flash("Invalid superbio token.")
            return redirect(url_for("ops.upload_query"))

    if use_pines:
        is_pines_available = init_pines_connection(superbio_api_token)
        if is_pines_available is False:
            # PINES could not load successfully
            flash("Could not load PINES server.")
            return redirect(url_for("ops.upload_query"))

    use_negation = False  # bool(request.form.get("view_negations"))
    hide_duplicates = not bool(request.form.get("keep_duplicates"))
    skip_after_event = bool(request.form.get("skip_after_event"))

    tag_query = {
        "exact": False,
        "nlp_apply": use_pines
    }
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
    superbio_api_token = session.get('superbio_api_token')

    # add task to the queue
    for patient in pt_ids:
        flask.current_app.task_queue.enqueue(
            nlp_processor.automatic_nlp_processor,
            args=(patient,),
            job_id=f'spacy:{patient}',
            description=f"Processing patient {patient} with spacy",
            retry=Retry(max=3),
            on_success=Callback(callback_job_success),
            on_failure=Callback(callback_job_failure),
            kwargs={
                "user": current_user.username,
                "job_id": f'spacy:{patient}',
                "superbio_api_token" : superbio_api_token,
                "description": f"Processing patient {patient} with spacy"
            }
        )
    return redirect(url_for("ops.get_job_status"))


def callback_job_success(job, connection, result, *args, **kwargs):
    '''
    A callback function to handle the event where
    a job from the task queue is completed successfully.
    '''
    db.report_success(job)

    if len(list(db.get_tasks_in_progress())) == 0:
        # Send a spin down request to the PINES Server if we are using superbio
        # This will occur when all tasks are completed
        if job.kwargs['superbio_api_token'] is not None:
            close_pines_connection(job.kwargs['superbio_api_token'])

def callback_job_failure(job, connection, result, *args, **kwargs):
    '''
    A callback function to handle the event where
    a job from the task queue has failed.
    '''
    db.report_failure(job)

    if len(list(db.get_tasks_in_progress())) == 0:
        # Send a spin down request to the PINES Server if we are using superbio
        # This will occur when all tasks are completed
        if job.kwargs['superbio_api_token'] is not None:
            close_pines_connection(job.kwargs['superbio_api_token'])

def init_pines_connection(superbio_api_token = None):
    '''
    Initializes the PINES url in the INFO col.
    If no server is available this is marked as None.

    Args :
        - superbio_api_token (str) : Access token for superbio server if one is being used.
    
    Returns :
        (bool) : True if a valid pines url has been found.
                            False if not valid pines url available.
    '''
    project_info = db.get_info()
    project_id = project_info["project_id"]

    try:
        pines_url, is_url_from_api = load_pines_url(project_id,
                                        superbio_api_token=superbio_api_token)
    except requests.exceptions.HTTPError as e:
        logger.error(f"Got HTTP error when trying to start PINES server : {e}")
        pines_url, is_url_from_api = None, False
    except Exception as e:
        logger.error(f"Got error when trying to access PINES server : {e}")
        pines_url, is_url_from_api = None, False

    db.create_pines_info(pines_url, is_url_from_api)
    if pines_url is not None:
        return True

    return False

def close_pines_connection(superbio_api_token):
    '''
    Closes the PINES server if using a superbio API.
    '''
    project_info = db.get_info()
    project_id = project_info["project_id"]
    token_status = get_token_status(superbio_api_token)

    if token_status['is_valid'] and token_status['has_expired'] is False:
        kill_pines_api(project_id, superbio_api_token)
    else:
        # If has_token_expired returns None (invalid token).
        logger.error("Cannot shut down remote PINES server with an API call as this is not a valid token.")

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
    patient_id = session['patient_id']

    def _update_event_date():
        new_date = request.form['date_entry']
        logger.info(f"Updating {patient_id}: {new_date}")
        db.update_event_date(patient_id, new_date, current_annotation_id)
        db.upsert_patient_results(patient_id)
        _adjudicate_annotation(updated_date = True)

    def _delete_event_date():
        db.upsert_patient_results(patient_id)
        db.delete_event_date(patient_id)

    def _move_to_previous_annotation(shift_value):
        def shift_index_backwards():
            new_index = session["index"] - shift_value
            session["index"] = max(0, new_index)
            session.modified = True

        return shift_index_backwards

    def _shift_first_index():
        session["index"] = 0
        session.modified = True

    def _shift_last_index():
        session["index"] = session["total_count"] - 1
        session.modified = True

    def _move_to_next_annotation(shift_value):
        def shift_index_forwards():
            new_index = session["index"] + shift_value
            session_index_max = session["total_count"] - 1
            session["index"] = min(session_index_max, new_index)
            session.modified = True

        return shift_index_forwards

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
            elif db.get_event_date(session["patient_id"]) is not None:
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
        db.add_comment(current_annotation_id, request.form['comment'].strip())


    actions = {
        'new_date': _update_event_date,
        'del_date': _delete_event_date,
        'comment': _add_annotation_comment,
        'first_anno': _shift_first_index,
        'prev_10': _move_to_previous_annotation(10),
        'prev_1': _move_to_previous_annotation(1),
        'next_1': _move_to_next_annotation(1),
        'next_10': _move_to_next_annotation(10),
        'last_anno': _shift_last_index,
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
            if db.get_patient_lock_status(session.get("patient_id")) is False:
                logger.info(f"Getting patient: {session.get('patient_id')} from session")
                return redirect(url_for("ops.show_annotation"))

            logger.info(f"Patient {session.get('patient_id')} is locked.")
            logger.info("Retrieving next patient.")

        patient_id = db.get_patients_to_annotate()
    else:
        if session.get("patient_id") is not None:
            db.set_patient_lock_status(session.get("patient_id"), False)
            session.pop("patient_id", None)

        search_patient = str(request.form.get("patient_id")).strip()
        is_patient_locked = False
        if search_patient and len(search_patient) > 0:
            patient = db.get_patient_by_id(search_patient)
            if patient is None:
                patient_id = None
            else:
                is_patient_locked = db.get_patient_lock_status(search_patient)
                if is_patient_locked is False:
                    patient_id = patient["patient_id"]
                else:
                    patient_id = None

        if patient_id is None:
            # if the search return no patient, get the next patient
            if is_patient_locked:
                flash(f"Patient {search_patient} is currently being reviewed by another user. Showing next patient")
            else:
                flash(f"Patient {search_patient} does not exist. Showing next patient")
            patient_id = db.get_patients_to_annotate()

    if patient_id is None:
        return render_template("ops/annotations_complete.html", **db.get_info())

    raw_annotations = db.get_all_annotations_for_patient(patient_id)
    hide_duplicates = db.get_search_query("hide_duplicates")
    res = format_annotations(raw_annotations, hide_duplicates)

    annotations = res["annotations"]
    total_count = res["total"]
    all_annotation_index = res["all_annotation_index"]
    unreviewed_annotations_index = res["unreviewed_annotations_index"]

    if total_count == 0:
        logger.info(f"Patient {patient_id} has no annotations. Showing next patient")
        flash(f"Patient {patient_id} has no annotations. Showing next patient")
        db.set_patient_lock_status(patient_id, False)
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

    db.set_patient_lock_status(patient_id, True)
    session.modified = True
    return redirect(url_for("ops.show_annotation"))

@bp.route("/unlock_patient", methods=["POST"])
def unlock_current_patient():
    """
    Sets the locked status of the patient in the session to False.
    """
    patient_id = session["patient_id"]
    if patient_id is not None:
        db.set_patient_lock_status(patient_id, False)
        session["patient_id"] = None
        return jsonify({"message": f"Unlocking patient # {patient_id}."}), 200

    return jsonify({"error": "No patient to unlock."}), 200

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

def get_highlighted_sentence(current_annotation, note):
    """
    Returns highlighted text for a sentence in a note.
    """
    highlighted_note = []
    text = note["text"]


    sentence_start = text.lower().index(current_annotation['sentence'])
    sentence_end = len(current_annotation['sentence'])

    # Take characters from the start of the sentence, excluding spaces and new lines.
    text = text[sentence_start:].strip()
    prev_end_index = 0

    annotations = db.get_all_annotations_for_sentence(note["text_id"],
                                                      current_annotation["sentence_number"])
    logger.info(annotations)

    for annotation in annotations:
        start_index = annotation['start_index']
        end_index = annotation['end_index']
        # Make sure the annotations don't overlap
        if start_index < prev_end_index:
            continue

        highlighted_note.append(text[prev_end_index:start_index])
        highlighted_note.append(f'<b><mark>{text[start_index:end_index]}</mark></b>')
        prev_end_index = end_index

    highlighted_note.append(text[prev_end_index:sentence_end])
    logger.info(highlighted_note)
    return " ".join(highlighted_note).strip().replace("\n", "<br>")

def format_annotations(annotations, hide_duplicates):
    """
    Formats annotations to keep only relevant occurrences as well
        as some additional data such as their review status.

    Args:
        annotations (list) : A list of all annotations for a paticular patient.
        hide_duplicates (bool) : True if we want to discard duplicate sentences
            from the annotations of this patient.
    Returns:
        result (dictionary) : A dictionary of all relevant annotations with some metadata.
    """
    if hide_duplicates:
        # If hide_duplicates sentences that are exact matches for sentences in
        # the same note are removed.

        # We first note the indices where duplicate sentences occur
        indices_to_remove = []
        seen_sentences = set()
        for i, annotation in enumerate(annotations):
            sentence = annotation['sentence'].lower().strip()
            if sentence in seen_sentences:
                indices_to_remove.append(i)
                continue

            seen_sentences.add(sentence)
    else:
        # If hide_duplicates is false then each sentence will still only be shown once.

        # We first note the indices where duplicate sentences occur
        indices_to_remove = []
        prev_note_id = None
        seen_sentence_indices = set()
        for i, annotation in enumerate(annotations):
            # If we are on a new note, then clear the hashset of sentences.
            # This is done so that we only check for the same sentence
            # in that note.
            if annotation['note_id'] != prev_note_id:
                seen_sentence_indices.clear()

            prev_note_id = annotation['note_id']
            sentence_index = annotation['sentence_start']
            if sentence_index in seen_sentence_indices:
                indices_to_remove.append(i)
                continue

            seen_sentence_indices.add(sentence_index)

    # Remove the indices in reverse order to avoid a later index changing
    # after a prior one is removed.
    indices_to_remove.sort(reverse=True)
    for index in indices_to_remove:
        # Mark the annotation as reviewed before poping it
        # This ensures that an unseen annotation cannot be unreviewed
        db.mark_annotation_reviewed(annotations[index]["_id"])
        annotations.pop(index)

    result = {
        "annotations": [],
        "all_annotation_index": [],
        "unreviewed_annotations_index": [],
        "total": 0
    }

    if len(annotations) > 0:
        result["annotations"] = [str(annotation["_id"]) for annotation in annotations]
        result["all_annotation_index"] = list(range(len(annotations)))
        # set array to 1 if annotation is unreviewed
        result["unreviewed_annotations_index"] = [1 if not x["reviewed"] else 0 for x in annotations]
        result["total"] = len(annotations)

    return result

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
