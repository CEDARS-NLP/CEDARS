"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import os
import re
import copy
from datetime import datetime, date
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

from .cedars_enums import ReviewStatus
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
from .database import s3, s3_resource
from .api import check_is_pines_available, kill_pines_api
from .api import get_token_status
from botocore.exceptions import ClientError
from .adjudication_handler import AdjudicationHandler
from .cedars_enums import PatientStatus
from .cedars_enums import log_function_call
import json
from datetime import datetime


bp = Blueprint("ops", __name__, url_prefix="/ops")
config = dotenv_values(".env")

logger.enable(__name__)

@log_function_call
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

@log_function_call
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

@log_function_call
def load_patient_data(patient_id):
    '''
    Loads all relevant info for a new patient to adjudicate
    from the database. These read calls have been organised into
    a seperate function to test DB read speeds.
    '''
    patient_data = {}
    patient_data['raw_annotations'] = db.get_all_annotations_for_patient(patient_id)
    patient_data['hide_duplicates'] = db.get_search_query("hide_duplicates")
    patient_data['stored_event_date'] = db.get_event_date(patient_id)
    patient_data['stored_annotation_id'] = db.get_event_annotation_id(patient_id)
    patient_data['patient_comments'] = db.get_patient_by_id(patient_id)["comments"]

    return patient_data

@bp.route("/project_details", methods=["GET", "POST"])
@auth.admin_required
@log_function_call
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
            return redirect("/")

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
                    return redirect("/")
            else:
                flash("Termination failed.. Please enter 'DELETE EVERYTHING' in confirmation")

    return render_template("ops/project_details.html",
                            **db.get_info())

@bp.route("/internal_processes", methods=["GET"])
@auth.admin_required
@log_function_call
def internal_processes():
    """
    This is a flask function for the backend logic for the internal_processes route.
    It is used by a technical admin to perform special technical operations the current project.
    """

    # Get the RQ_DASHBOARD_URL environment variable,
    # if it does not exist use /rq as a default.
    rq_dashboard_url = os.getenv("RQ_DASHBOARD_URL", "/rq")

    return render_template("ops/internal_processes.html",
                            rq_dashboard_url = rq_dashboard_url,
                            **db.get_info())

@log_function_call
def read_gz_csv(filename, *args, **kwargs):
    '''
    Function to read a GZIP compressed csv to a pandas DataFrame.
    '''
    return pd.read_csv(filename, compression='gzip', *args, **kwargs)

@log_function_call
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
        # Log the filepath and prepare the local temp directory
        logger.info(filepath)
        local_directory = tempfile.gettempdir()
        os.makedirs(local_directory, exist_ok=True)
        local_filename = os.path.join(local_directory, os.path.basename(filepath))

        # Download the file from S3
        s3.download_file(g.bucket_name, filepath, local_filename)
        logger.info(f"File downloaded successfully to {local_filename}")

        # Process the file depending on its extension
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
        # Clean up the downloaded local file
        if os.path.exists(local_filename):
            os.remove(local_filename)
            logger.info(f"Removed temporary file: {local_filename}")

@log_function_call
def prepare_note(note_info):
    logger.debug(f"Formatting note info for note {note_info['text_id']}.")
    date_format = '%Y-%m-%d'
    note_info["text_date"] = datetime.strptime(note_info["text_date"], date_format)
    note_info["reviewed"] = False
    note_info["text_id"] = str(note_info["text_id"]).strip()
    note_info["patient_id"] = str(note_info["patient_id"]).strip()
    return note_info

@log_function_call
def prepare_patients(patient_ids):
    return [str(p_id).strip() for p_id in patient_ids]

@log_function_call
def EMR_to_mongodb(filepath, chunk_size_insert_notes=1000, chunk_size_upsert_patients=2000):
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
    all_patient_ids = []

    try:
        for chunk in load_pandas_dataframe(filepath, chunk_size_insert_notes):
            total_chunks += 1
            rows_in_chunk = len(chunk)
            total_rows += rows_in_chunk

            logger.info(f"Processing chunk {total_chunks} with {rows_in_chunk} rows")

            # Prepare notes
            notes_to_insert = [prepare_note(row.to_dict()) for _, row in chunk.iterrows()]

            # Collect patient IDs
            chunk_patient_ids = list(chunk['patient_id'].unique())
            chunk_patient_ids = prepare_patients(chunk_patient_ids)
            all_patient_ids.extend(chunk_patient_ids)

            # Bulk insert notes
            inserted_count = db.bulk_insert_notes(notes_to_insert)
            logger.info(f"Inserted {inserted_count} notes from chunk {total_chunks}")

        # store NOTES_SUMMARY such as first_note_date, last_note_date, total_notes etc.
        # to use a cache
        notes_summary_count = db.update_notes_summary()
        logger.info(f"Updated {notes_summary_count} notes summary")
        # Bulk upsert patients
        upserted_count_patients, _ = db.bulk_upsert_patients(all_patient_ids, chunk_size_upsert_patients)
        logger.info(f"Upserted {upserted_count_patients} patients")
        logger.info(f"Completed document migration to MongoDB database. "
                    f"Total rows processed: {total_rows}, "
                    f"Total chunks processed: {total_chunks}, "
                    f"Total unique patients: {len(all_patient_ids)}")

    except Exception as e:
        logger.error(f"An error occurred during document migration: {str(e)}")
        flash(f"Failed to upload data: {str(e)}")
        raise

@bp.route("/upload_data", methods=["GET", "POST"])
@auth.admin_required
@log_function_call
def upload_data():
    """
    This is a flask function for the backend logic to upload a file to the database.
    """
    filename = None
    if request.method == "POST":
        # if db.get_task(f"upload_and_process:{current_user.username}"):
        #     flash("A file is already being processed.")
        #     return redirect(request.url)
        s3_file = request.form.get("miniofile")
        if s3_file != "None" and s3_file is not None:
            logger.info(f"Using S3 file: {s3_file}")
            filename = s3_file
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
                # Upload the file to S3 using Boto3
                s3.upload_fileobj(
                    Fileobj=file,      
                    Bucket=g.bucket_name,  
                    Key=filename,      
                    ExtraArgs={"ContentType": file.content_type}  
                )
        
                logger.info(f"File - {file.filename} uploaded successfully.")
                flash(f"{filename} uploaded successfully.")
            except Exception as e:
                filename = None
                flash(f"Failed to upload file: {str(e)}")
                return redirect(request.url)

        if filename:
            try:
                chunk_size_insert_notes = int(os.getenv("CHUNK_SIZE_INSERT_NOTES"))
                chunk_size_upsert_patients = int(os.getenv("CHUNK_SIZE_UPSERT_PATIENTS"))
                EMR_to_mongodb(filename, chunk_size_insert_notes, chunk_size_upsert_patients)
                flash(f"Data from {filename} uploaded to the database.")
                return redirect(url_for('ops.upload_query'))
            except Exception as e:
                flash(f"Failed to upload data: {str(e)}")
                return redirect(request.url)
    try:
         # List objects in the specified S3 bucket with the given prefix
            response = s3.list_objects_v2(
                Bucket=g.bucket_name,
                Prefix="uploaded_files/"
            )

            # Extract the file names and sizes
            if 'Contents' in response:
                files = [(obj['Key'], obj['Size']) for obj in response['Contents']]
            else:
                files = [] 
    except Exception as e:
        flash(f"Error listing files: {e}")
        files = []

    return render_template("ops/upload_file.html", files=files, **db.get_info())


@bp.route("/upload_query", methods=["GET", "POST"])
@auth.admin_required
@log_function_call
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
    logger.info(f"Received search query: {search_query}")
    search_query_pattern = r'^\s*(\(\s*[a-zsA-Z0-9*?]+(\s+AND\s+[a-zA-Z0-9*?]+)*\s*\)|[a-zA-Z0-9*?]+)(\s*OR\s+(\(\s*[a-zA-Z0-9*?]+(\s+AND\s+[a-zA-Z0-9*?]+)*\s*\)|[a-zA-Z0-9*?]+))*\s*$'
    try:
        re.match(search_query_pattern, search_query)
    except re.error as e:
        flash(f"Invalid query - {e}")
        logger.debug(f"Invalid query: {e}")
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

@bp.route("/init_pines", methods=["POST"])
@log_function_call
def ConnectToPines():
    use_pines = bool(request.form.get("nlp_apply"))
    superbio_api_token = session.get('superbio_api_token')

    try:
        is_pines_available = check_is_pines_available(superbio_api_token)
        if use_pines:
            # Return JSON response based on connection status
            if is_pines_available:
                logger.info(f"PINES EC2 instance is available now")
                return jsonify({"status": "success"})
            else:
                logger.info(f"PINES EC2 instance is not up and running yet")
                return jsonify({"status": "failed"}) 
            
    except Exception as e:
        logger.error(f"Error while connecting to PINES: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

def send_shutdown_msg():
    logger.info("All the notes were processed successfully from the task queue - Shutdown EC2")

@bp.route("/shutdown_pines", methods=["POST"])
@log_function_call
def shutdown_pines():
    logger.info(f"Sending command to shutdown PINES EC2 instance")

    # Call send_shutdown_msg and enqueue it so that both the frontend and worker logs reflect the command
    send_shutdown_msg()
    job = flask.current_app.ops_queue.enqueue(
        send_shutdown_msg,
    )
    return redirect("/ops/internal_processes")
           

@bp.route("/start_process")
@log_function_call
def do_nlp_processing():
    """
    Run NLP workers
    TODO: requeue failed jobs
    """
    nlp_processor = nlpprocessor.NlpProcessor()
    pt_ids = db.get_patient_ids()
    superbio_api_token = session.get('superbio_api_token')
    usePines = db.get_search_query("tag_query").get('nlp_apply', False)
    # when comes from superbio api
    if superbio_api_token is not None or usePines is False:
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
    else: #in case of usePines with aws - we need to shutdown EC2 instance of success/failure of the task queue
        # add task to the queue
        for patient in pt_ids:
            flask.current_app.task_queue.enqueue(
                nlp_processor.automatic_nlp_processor,
                args=(patient,),
                job_id=f'spacy:{patient}',
                description=f"Processing patient {patient} with spacy",
                retry=Retry(max=3),
                on_success=Callback(callback_job_success_lambda),
                on_failure=Callback(callback_job_failure_lambda),
                kwargs={
                    "user": current_user.username,
                    "job_id": f'spacy:{patient}',
                    "description": f"Processing patient {patient} with spacy"
                }
            )
                
    return redirect(url_for("ops.get_job_status"))

@log_function_call
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

@log_function_call
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

@log_function_call
def callback_job_success_lambda(job, connection, result, *args, **kwargs):
    '''
    A callback function to shutdown EC2 intance. event where
    a job from the task queue is completed successfully so we can shutdown EC2 instance.
    '''
    db.report_success(job)

    if len(list(db.get_tasks_in_progress())) == 0:
        # Send a spin down request to the AWS Lambda to shutdown EC2 instance 
        check_all_tasks_completed()
        

@log_function_call
def callback_job_failure_lambda(job, connection, result, *args, **kwargs):
    '''
    A callback function to handle the event where
    a job from the task queue has failed.
    '''
    db.report_failure(job)

    if len(list(db.get_tasks_in_progress())) == 0:
        # Send a spin down request to the AWS Lambda to shutdown EC2 instance 
        check_all_tasks_completed()


@log_function_call
def check_all_tasks_completed():
    # Access the queue and registries
    queue = flask.current_app.task_queue
    failed_registry = FailedJobRegistry(queue=queue)

    # Check the total jobs remaining in the queue
    total_jobs = len(queue.job_ids)
    failed_jobs_count = len(failed_registry)
    usePines = db.get_search_query("tag_query").get('nlp_apply', False)
    logger.info(f"usePines: {usePines}, total jobs: {total_jobs}, failed jobs: {failed_jobs_count}")

    if usePines: # log this only when using pines to execute search
        if total_jobs == 0: # all the tasks has been processed successfully
            if failed_jobs_count == 0: #all the tasks were successful
                logger.info("All the notes were processed successfully from the task queue - Shutdown EC2")
            else: # some of the tasks failed in the queue.
                logger.info("All the notes were processed from the task queue with some failure - Shutdown EC2")
        else:
                logger.info("Some tasks are still running or queued.")

    
@log_function_call
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
@log_function_call
def get_job_status():
    """
    Directs the user to the job status page.
    """
    return render_template("ops/job_status.html",
                           tasks=db.get_tasks_in_progress(), **db.get_info())


@bp.route('/queue_stats', methods=['GET'])
@log_function_call
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

@log_function_call
def backup_session_data(patient_id, patient_data,
                        reviewed_annotation_ids, patient_comments,
                        skip_after_event):
    """Backup session data to a file"""
    try:
        backup_dir = os.path.join(flask.current_app.instance_path, 'session_backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_file = os.path.join(backup_dir, f'session.json')
        patient_data['review_statuses'] = [str(x.value) for x in patient_data['review_statuses']]
        backup_data = {
            'patient_id': patient_id,
            'patient_data': patient_data,
            'reviewed_annotation_ids' : reviewed_annotation_ids,
            'patient_comments' : patient_comments,
            'skip_after_event' : skip_after_event,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f)
            
        logger.info(f"Backed up session data for patient {patient_id}")
    except Exception as e:
        logger.error(f"Failed to backup session data: {str(e)}")

@log_function_call
def restore_session_data():
    """Restore session data from backup file"""
    try:
        backup_dir = os.path.join(flask.current_app.instance_path, 'session_backups')
        backup_file = os.path.join(backup_dir, f'session.json')
        
        if os.path.exists(backup_file):
            with open(backup_file, 'r') as f:
                backup_data = json.load(f)
            backup_data['patient_data']['review_statuses'] = [ReviewStatus(int(x)) for x in backup_data['patient_data']['review_statuses']]
                
            # Only restore if the backup is less than 1 hour old
            backup_time = datetime.fromisoformat(backup_data['timestamp'])
            if (datetime.now() - backup_time).total_seconds() < 3600:
                session['patient_id'] = backup_data['patient_id']
                session['patient_data'] = backup_data['patient_data']
                session['reviewed_annotation_ids'] = backup_data['reviewed_annotation_ids']
                session['patient_comments'] = backup_data['patient_comments']
                session['skip_after_event'] = backup_data['skip_after_event']
                logger.info(f"Restored session data for patient")
                return True
            else:
                logger.warning(f"Backup for patient is too old")
                os.remove(backup_file)  # Clean up old backup
        return False
    except Exception as e:
        logger.error(f"Failed to restore session data: {str(e)}")
        return False

@log_function_call
def update_patient_data(patient_id, comments, reviewed_by,
                        reviewed_annotation_ids, timestamp):
    '''
    Updates the comments, results and list of reviewed annotations for
    a patient in the database. This function will also automatically unlock
    the patient after the updates have been made.
    Args:
        - patient_id (str) : Unique ID for the patient.
        - comment (str) : Text of the comment on this annotation.
        - annotation_ids (list[str]) : Unique IDs for the annotations that
                                        have been reviewed.
        - reviewed_by (str) : The name of the user who reviewed these annotations.
        - timestamp (datetime obj) : The timestamp at which this information was entered.
    '''

    db.batch_mark_annotation_reviewed(reviewed_annotation_ids,
                                       reviewed_by)
    db.add_comment(patient_id, comments.strip())

    db.upsert_patient_records(patient_id,
                             timestamp,
                             reviewed_by
                    )
    db.set_patient_lock_status(patient_id, False)

@log_function_call
def enter_patient_date(patient_id, new_date,
                       current_annotation_id, reviewed_by,
                       comments, reviewed_annotation_ids,
                       timestamp, skip_after_event,
                       is_patient_reviewed):
    '''
    Enters the new event date in the database and marks
    any relevant annotations as skipped or reviewed.
    This will additionally call the 'update_patient_data'
    function to unlock the patient and enter any other
    relevant information into the database.
    Args:
        - patient_id (str) : Unique ID for the patient.
        - new_date (datetime obj) : New event date for this patient
        - current_annotation_id (str) : Annotation ID at which the date was entered.
        - reviewed_by (str) : The name of the user who reviewed these annotations.
        - comment (str) : Text of the comment on this annotation.
        - reviewed_annotation_ids (list[str]) : Unique IDs for the annotations that
                                        have been reviewed.
        - timestamp (datetime obj) : The timestamp at which this information was entered.
        - skip_after_event (bool) : True if we need to skip unreviewed annotations that
                                        occur after the event date.
        - is_patient_reviewed (bool) : True if the patient review is finished and
                                        the patient results will need to be entered.
                                        The patient will also be unlocked after the
                                        DB updates.
    '''

    if skip_after_event:
        db.mark_annotations_post_event(patient_id, new_date)

    db.mark_annotation_reviewed(current_annotation_id, reviewed_by)
    db.update_event_date(patient_id, new_date, current_annotation_id)

    if is_patient_reviewed:
        update_patient_data(patient_id, comments, reviewed_by,
                        reviewed_annotation_ids, timestamp)

@log_function_call
def delete_patient_date(patient_id,
                       current_annotation_id, reviewed_by,
                       comments, reviewed_annotation_ids,
                       timestamp, is_patient_reviewed):
    '''
    Enters the new event date in the database and marks
    any relevant annotations as skipped or reviewed.
    This will additionally call the 'update_patient_data'
    function to unlock the patient and enter any other
    relevant information into the database.
    Args:
        - patient_id (str) : Unique ID for the patient.
        - current_annotation_id (str) : Annotation ID at which the date was deleted.
        - reviewed_by (str) : The name of the user who reviewed these annotations.
        - comment (str) : Text of the comment on this annotation.
        - reviewed_annotation_ids (list[str]) : Unique IDs for the annotations that
                                        have been reviewed.
        - timestamp (datetime obj) : The timestamp at which this information was entered.
        - is_patient_reviewed (bool) : True if the patient review is finished and
                                        the patient results will need to be entered.
                                        The patient will also be unlocked after the
                                        DB updates.
    '''
    db.delete_event_date(patient_id)
    db.revert_skipped_annotations(patient_id)
    db.revert_annotation_reviewed(current_annotation_id, reviewed_by)

    if is_patient_reviewed:
        update_patient_data(patient_id, comments, reviewed_by,
                        reviewed_annotation_ids, timestamp)

@bp.route("/save_adjudications", methods=["GET", "POST"])
@login_required
@log_function_call
def save_adjudications():
    """
    Handle logic for the save_adjudications route.
    Used to edit and review annotations.
    """
    if session.get("patient_id") is None:
        if restore_session_data():
            logger.info("Session restored from backup")
        else:
            logger.error("No patient_id found in session and no backup found")
            return redirect(url_for("ops.adjudicate_records"))

    logger.info(f"Saving adjudications for patient {session['patient_id']}")
    adjudication_handler = AdjudicationHandler(session['patient_id'])
    adjudication_handler.load_from_patient_data(session['patient_id'],
                                                session['patient_data'])

    current_annotation_id = adjudication_handler.get_curr_annotation_id()
    session['patient_comments'] = request.form['comment'].strip()
    patient_id = session['patient_id']
    skip_after_event = session['skip_after_event']

    action = request.form['submit_button']
    # The 'db_results_updated' flag is set to True if we enqueue a function that
    # will automatically update all the patient results in the database.
    # This will prevent us from enqueuing another update job later
    # if one is already entered to avoid data conflicts
    db_results_updated = False

    is_shift_performed = False
    if action == 'new_date':
        logger.debug(f"Entering a new date for patient {session['patient_id']}")
        # Make sure to remove all skipped markings before a new date is entered
        db.revert_skipped_annotations(patient_id)
        adjudication_handler.reset_all_skipped()

        new_date = request.form['date_entry']
        date_format = '%Y-%m-%d'
        new_date = datetime.strptime(new_date, date_format)
        annotations_after_event = []
        if skip_after_event:
            annotations_after_event = db.get_annotations_post_event(patient_id,
                                                                    new_date)

        db_results_updated = True
        adjudication_handler.mark_event_date(new_date, current_annotation_id,
                                             annotations_after_event)
        flask.current_app.ops_queue.enqueue(enter_patient_date,
                                            patient_id, new_date,
                                            current_annotation_id,
                                            current_user.username,
                                            session['patient_comments'],
                                            session['reviewed_annotation_ids'],
                                            datetime.now(),
                                            skip_after_event,
                                            adjudication_handler.is_patient_reviewed())

    elif action == 'del_date':
        logger.debug(f"Deleting saved date for patient {session['patient_id']}")
        db_results_updated = True
        adjudication_handler.delete_event_date()
        flask.current_app.ops_queue.enqueue(delete_patient_date,
                                            patient_id,
                                            current_annotation_id,
                                            current_user.username,
                                            session['patient_comments'],
                                            session['reviewed_annotation_ids'],
                                            datetime.now(),
                                            adjudication_handler.is_patient_reviewed())
    elif action == 'adjudicate':
        logger.debug(f"Adjudicating annotation {current_annotation_id} for {session['patient_id']}")
        session['reviewed_annotation_ids'].append(current_annotation_id)
        adjudication_handler._adjudicate_annotation()
    else:
        logger.debug(f"Shifting between annotations for patient {session['patient_id']}")
        # Must be a shift action
        adjudication_handler.perform_shift(action)
        is_shift_performed = True

    session["patient_data"] = adjudication_handler.get_patient_data()

    try:
        patient_data_cloned = copy.deepcopy(session['patient_data'])
        review_status_cloned = copy.deepcopy(session['reviewed_annotation_ids'])
        patient_comments_cloned = copy.deepcopy(session['patient_comments'])
        skip_after_event_cloned = copy.deepcopy(session['skip_after_event'])
        backup_session_data(session['patient_id'], patient_data_cloned,
                        review_status_cloned, patient_comments_cloned,
                        skip_after_event_cloned)
    except Exception as e:
        logger.error(f"Failed to backup session data: {str(e)}")

    # We do not skip to the next patient if the current operation was just a shift.
    # This is done as users may want to view notes for a patient that has already been
    # reviewed.
    if adjudication_handler.is_patient_reviewed() and not is_shift_performed:
        db.mark_patient_reviewed(patient_id, reviewed_by=current_user.username)
        if not db_results_updated:
            flask.current_app.ops_queue.enqueue(update_patient_data,
                                            session['patient_id'],
                                            session['patient_comments'],
                                            current_user.username,
                                            session['reviewed_annotation_ids'],
                                            datetime.now())

        session.pop("patient_id")
        session.pop("patient_data")
        session.pop("reviewed_annotation_ids")

    session.modified = True

    # the session has been cleared so get the next patient
    if session.get("patient_id") is None:
        return redirect(url_for("ops.adjudicate_records"))

    return redirect(url_for("ops.show_annotation"))


@bp.route("/show_annotation", methods=["GET"])
@login_required
@log_function_call
def show_annotation():
    """
    Formats and displays the current annotation being viewed by the user.
    """
    if session.get("patient_id") is None:
        return redirect(url_for("ops.adjudicate_records"))

    logger.info(f"Presenting annotation for patient {session['patient_id']}")

    index = session.get("index", 0)
    adjudication_handler = AdjudicationHandler(session['patient_id'])
    adjudication_handler.load_from_patient_data(session['patient_id'],
                                                session['patient_data'])
    annotation_id = adjudication_handler.get_curr_annotation_id()

    annotation = adjudication_handler.get_curr_annotation()
    note = db.get_annotation_note(annotation_id)
    if not note:
        flash("Annotation note not found.")
        return redirect(url_for("ops.adjudicate_records"))

    comments = session['patient_comments']
    annotations_for_note = adjudication_handler.get_all_annotations_for_curr_note()
    annotations_for_sentence = adjudication_handler.get_all_annotations_for_curr_sentence()

    annotation_data = adjudication_handler.get_annotation_details(annotation,
                                                                  note, comments,
                                                                  annotations_for_note,
                                                                  annotations_for_sentence)

    return render_template("ops/adjudicate_records.html",
                           name = current_user.username,
                           project = session['project_name'],
                           **annotation_data)


@bp.route("/adjudicate_records", methods=["GET", "POST"])
@login_required
@log_function_call
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
    logger.info("Getting patient to adjudicate.")

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
            if session.get('patient_comments') is not None:
                db.add_comment(session["patient_id"], session['patient_comments'].strip())
            if session.get('reviewed_annotation_ids') is not None:
                db.batch_mark_annotation_reviewed(session['reviewed_annotation_ids'],
                                                    current_user.username)
            results_update_job = flask.current_app.ops_queue.enqueue(
                db.upsert_patient_records, session.get("patient_id"),
                datetime.now(), current_user.username
            )
            db.set_patient_lock_status(session.get("patient_id"), False)
            session.pop("patient_id", None)
            session.pop("patient_data", None)
            session.modified = True

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

    logger.info(f"Fetching annotations for patient {patient_id}.")

    # Read raw info for new patient from the db
    raw_patient_data = load_patient_data(patient_id)
    raw_annotations = raw_patient_data['raw_annotations']
    hide_duplicates = raw_patient_data['hide_duplicates']
    stored_event_date = raw_patient_data['stored_event_date']
    stored_annotation_id = raw_patient_data['stored_annotation_id']
    patient_comments = raw_patient_data['patient_comments']

    logger.info(f"Creating adjudication handler for patient {patient_id}.")
    adjudication_handler = AdjudicationHandler(patient_id)
    patient_data, annotations_with_duplicates = adjudication_handler.init_patient_data(raw_annotations,
                                           hide_duplicates, stored_event_date,
                                           stored_annotation_id)

    db.batch_mark_annotation_reviewed(annotations_with_duplicates, current_user.username)
    
    logger.info(f"Finished loading adjudication handler for patient {patient_id}.")

    if len(patient_data["annotation_ids"]) > 0:
        # Only lock the patient for annotation if
        # there are annotations that exist
        db.set_patient_lock_status(patient_id, True)

    patient_status = adjudication_handler.get_patient_status()
    session['project_name'] = db.get_info()['project']

    if patient_status == PatientStatus.NO_ANNOTATIONS:
        logger.info(f"Patient {patient_id} has no annotations. Showing next patient")
        flash(f"Patient {patient_id} has no annotations. Showing next patient")
        results_update_job = flask.current_app.ops_queue.enqueue(
                db.upsert_patient_records, patient_id,
                datetime.now(), current_user.username
            )
        db.set_patient_lock_status(patient_id, False)
        return redirect(url_for("ops.adjudicate_records"))

    elif patient_status == PatientStatus.REVIEWED_WITH_EVENT:
        flash(f"Patient {patient_id} has been reviewed. Showing annotation where event date was marked. ")
        logger.info(f"Showing annotations for patient {patient_id}.")
        session["patient_id"] = patient_id
        session['patient_data'] = patient_data
        session['reviewed_annotation_ids'] = []
        session['patient_comments'] = patient_comments
        session['skip_after_event'] = db.get_search_query(query_key="skip_after_event")

    elif patient_status == PatientStatus.REVIEWED_NO_EVENT:
        flash(f"Patient {patient_id} has no annotations left to review. Showing all annotations.")
        session["patient_id"] = patient_id
        session['patient_data'] = patient_data
        session['reviewed_annotation_ids'] = []
        session['patient_comments'] = patient_comments
        session['skip_after_event'] = db.get_search_query(query_key="skip_after_event")

    else:
        logger.info(f"Showing annotations for patient {patient_id}.")
        session["patient_id"] = patient_id
        session['patient_data'] = patient_data
        session['reviewed_annotation_ids'] = []
        session['patient_comments'] = patient_comments
        session['skip_after_event'] = db.get_search_query(query_key="skip_after_event")

    session.modified = True
    return redirect(url_for("ops.show_annotation"))

@bp.route("/unlock_patient", methods=["GET", "POST"])
@log_function_call
def unlock_current_patient():
    """
    Sets the locked status of the patient in the session to False.
    """
    patient_id = session.get("patient_id")
    message = "No patient to unlock."
    if patient_id is not None:
        if session.get('patient_comments') is not None:
                db.add_comment(patient_id, session['patient_comments'].strip())

        if session.get('reviewed_annotation_ids') is not None:
                db.batch_mark_annotation_reviewed(session['reviewed_annotation_ids'],
                                                    current_user.username)
        results_update_job = flask.current_app.ops_queue.enqueue(
                db.upsert_patient_records, patient_id,
                datetime.now(), current_user.username
            )
        db.set_patient_lock_status(patient_id, False)
        session["patient_id"] = None
        message = f"Unlocking patient # {patient_id}."

    if request.method == "GET":
        message += " Unlock triggered due to inactivity."
        flash(message)
        return redirect("/stats/")
    else:
        return jsonify({"message": message}), 200

@log_function_call
def get_download_filename(is_full_download=False):
    '''
    Returns the filename for a new download task.

    Args :
        - is_full_download (bool) : True if all of the results 
                                    (including the key sentences)
                                    are to be downloaded.

    Returns :
        - filename (string) : A string in the format
                              {project_name}_{timestamp}_{downloadtype}.csv
    '''
    project_name = db.get_proj_name()
    timestamp = datetime.now()
    timestamp = timestamp.strftime("%Y-%m-%d_%H_%M_%S")

    if is_full_download:
        return f"annotations_full_{project_name}_{timestamp}.csv"

    return f"annotations_compact_{project_name}_{timestamp}.csv"

@bp.route('/download_page')
@bp.route('/download_page/<job_id>')
@auth.admin_required
@log_function_call
def download_page(job_id=None):
    """
    Loads the page where an admin can download the results
    of annotations made for that project.
    """
    files = []

    try:
        # List objects in the specified S3 bucket with the given prefix
        response = s3.list_objects_v2(
            Bucket=g.bucket_name,
            Prefix="annotated_files/"
        )

        # Extract the file names, sizes, and modified times
        if 'Contents' in response:
            for obj in response['Contents']:
                file_name = obj['Key'].rsplit("/", 1)[-1] 
                size = obj['Size'] 
                last_modified = obj['LastModified'].strftime("%Y-%m-%d %H:%M:%S") 

                # Append to the files list
                files.append((file_name, size, last_modified))

    except Exception as e:
        flash(f"Error listing files: {str(e)}")

    if job_id is not None:
        return flask.jsonify({"files": files}), 202

    return render_template('ops/download.html', job_id=job_id, files=files, **db.get_info())


@bp.route('/download_annotations', methods=["POST"])
@auth.admin_required
@log_function_call
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
        
    response = s3.get_object(Bucket=g.bucket_name, Key=f"annotated_files/{filename}")     
    file = response['Body'].read()
    logger.info(f"Downloaded annotations from S3: {filename}")
    return flask.Response(
        file,
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename=cedars_{filename}"}
    )


@bp.route('/create_download_task', methods=["GET"])
@auth.admin_required
@log_function_call
def create_download():
    """
    Create a download task for annotations
    """

    download_filename = get_download_filename()
    job = flask.current_app.ops_queue.enqueue(
        db.download_annotations, download_filename,
    )
    return flask.jsonify({'job_id': job.get_id()}), 202


@bp.route('/create_download_task_full', methods=["GET"])
@auth.admin_required
@log_function_call
def create_download_full():
    """
    Create a download task for annotations
    """

    download_filename = get_download_filename(True)
    job = flask.current_app.ops_queue.enqueue(
        db.download_annotations, download_filename, True
    )

    return flask.jsonify({'job_id': job.get_id()}), 202

@bp.route('/delete_download_file', methods=["POST"])
@auth.admin_required
@log_function_call
def delete_download_file():
    """
    Deletes a download file from the current S3 bucket.
    """
    try:
        filename = "annotated_files/"+request.form.get("filename")
        S3_bucket=s3_resource.Bucket(g.bucket_name)
        response = S3_bucket.object_versions.filter(Prefix=filename).delete()
        logger.info(f"S3 delete object Response: '{response}'")
        logger.info(f"Permanently deleted all versions of object '{filename}'")
        return redirect("/ops/download_page")
    except ClientError as e:
         flash(f"Error deleting file '{filename}' from bucket '{g.bucket_name}': {e}")
         error_code = e.response['Error']['Code']
         if error_code == 'NoSuchKey':
            logger.info(f"File '{filename}' not found in bucket '{g.bucket_name}'")
            return redirect(request.url)
         elif error_code == 'AccessDenied':
            logger.info(f"Access denied while deleting file '{filename}' from bucket '{g.bucket_name}'")
            return redirect(request.url)
         else:
            logger.info(f"Error deleting file '{filename}' from bucket '{g.bucket_name}': {e}")
            return redirect(request.url)
       
@bp.route('/update_results_collection', methods=["GET"])
@auth.admin_required
@log_function_call
def update_results_collection():
    """
    Creates and updates the RESULTS collection.
    """

    logger.info("Creating job to update results collection.")
    job = flask.current_app.ops_queue.enqueue(db.update_patient_results,
                                                True)

    return flask.jsonify({'job_id': job.get_id()}), 202

@bp.route('/unlock_all_patients', methods=["GET"])
@auth.admin_required
@log_function_call
def run_unlock_all_patients():
    """
    Unlocks all patients in the database.
    NOTE : This can break the application if run while users are still annotating patients.
    """

    logger.info("Creating job to unlock all patients in the PATIENTS collection.")
    job = flask.current_app.ops_queue.enqueue(db.remove_all_locked)

    return flask.jsonify({'unlock_job_id': job.get_id()}), 202

@bp.route('/check_job/<job_id>')
@auth.admin_required
@log_function_call
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
