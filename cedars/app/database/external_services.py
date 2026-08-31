'''
external_services.py

Functions from db.py that call out to external systems (the PINES HTTP API,
RQ job objects) rather than only reading/writing the database. Kept separate
from the pure-DB modules; these call into db_search/db_inserts/db_tasks for
their database-facing steps.
'''

import re
from time import sleep
from typing import Optional

import requests
from loguru import logger
from sqlalchemy import select

from ..cedars_enums import log_function_call
from .db_inserts import insert_pines_prediction
from .db_search import get_note_prediction_from_db
from .db_session import session_scope
from .db_tasks import update_db_task_progress
from .project_table_creation import Notes

logger.enable(__name__)


@log_function_call
def get_prediction(pines_url: str, note: str) -> tuple[float, float]:
    '''
    Calls the PINES /predict HTTP endpoint for a single note's text.
    Retries up to 3 times (with a 300s backoff) on a 502 response.

    Returns:
        tuple[float, float]: (score, classification_threshold)
    '''
    url = f"{pines_url}/predict"
    data = {"text": note}
    log_notes = None
    try:
        logger.info(f"Calling PINES /predict endpoint at: {url}")
        response = requests.post(url, json=data, timeout=3600, verify=False)
        request_status = response.status_code
        logger.debug(f"Got response code {request_status} from URL {url}.")

        if request_status == 502:
            for num_retries in range(1, 4):
                # A 502 can mean the PINES server is overloaded; wait and retry.
                logger.info("Got PINES request status 502, sleeping for 300s before retrying.")
                sleep(300)
                logger.info(f"Trying to reach {url}. Retry no: {num_retries}")
                response = requests.post(url, json=data, timeout=3600, verify=False)
                request_status = response.status_code
                if request_status != 502:
                    break

        response.raise_for_status()
        res = response.json()["prediction"]
        score = res.get("score")
        label = res.get("label")
        clf_threshold = res.get("classification_threshold")
        if isinstance(label, str):
            score = 1 - score if "0" in label else score
        else:
            score = 1 - score if label == 0 else score

        log_notes = re.sub(r'\d', '*', note[:20])
        logger.debug(f"Got prediction for note: {log_notes} with score: {score} and label: {label}")
        return score, clf_threshold
    except requests.exceptions.RequestException as exc:
        logger.error(f"Failed to get prediction for note: {log_notes}")
        raise exc


@log_function_call
def predict_and_save(project_engine, pines_url: str, text_ids: Optional[list[str]] = None,
                     force_update: bool = False) -> Optional[float]:
    '''
    Predicts a PINES score for every requested note (or all notes, if
    `text_ids` is None) that doesn't already have a stored prediction, and
    saves each result to the PINES table.

    Returns:
        The last classification_threshold seen, or None if nothing was predicted.
    '''
    with session_scope(project_engine) as session:
        stmt = select(Notes)
        if text_ids is not None:
            stmt = stmt.where(Notes.text_id.in_(text_ids))
        notes = session.execute(stmt).scalars().all()
        note_dicts = [{
            "text_id": n.text_id,
            "text": n.text,
            "text_date": n.text_date,
            "patient_id": n.patient_id,
            "text_tag_1": n.text_tag_1,
            "text_tag_3": n.text_tag_3,
        } for n in notes]

    clf_threshold = None
    for note in note_dicts:
        text_id = note["text_id"]
        if force_update or get_note_prediction_from_db(project_engine, text_id) is None:
            logger.info(f"Predicting for note: {text_id}")
            prediction, clf_threshold = get_prediction(pines_url, note["text"])
            insert_pines_prediction(
                project_engine,
                text_id=text_id,
                patient_id=note["patient_id"],
                text_date=note["text_date"],
                predicted_score=prediction,
                report_type=note["text_tag_3"],
                document_type=note["text_tag_1"],
            )

    return clf_threshold


@log_function_call
def report_success(project_engine, job) -> None:
    '''
    Records that an RQ job completed successfully.
    '''
    job.meta['progress'] = 100
    job.save_meta()
    update_db_task_progress(project_engine, job.get_id(), 100, failed=False)


@log_function_call
def report_failure(project_engine, job) -> None:
    '''
    Records that an RQ job failed. Failures are terminal and must not remain
    counted as "in progress".
    '''
    job.meta['progress'] = 0
    job.save_meta()
    update_db_task_progress(project_engine, job.get_id(), 0, failed=True)
