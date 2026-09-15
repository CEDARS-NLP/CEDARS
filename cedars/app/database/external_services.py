'''
external_services.py

Functions that call out to external systems (the PINES HTTP API, RQ job
objects) rather than only reading/writing the database. Kept separate from the
pure-DB modules; these call into db_search/db_inserts/db_tasks for their
database-facing steps.
'''

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
def get_prediction(pines_url: str, note: str) -> tuple[float, str, str, float]:
    '''
    Calls the PINES /predict HTTP endpoint for a single note's text.
    Retries transient connection and 502/503 failures up to 3 times.

    Returns:
        (positive-class score, label, model name, classification threshold)
    '''
    url = f"{pines_url}/predict"
    data = {"text": note}
    last_error = None
    for attempt in range(1, 4):
        try:
            logger.info(f"Calling PINES /predict endpoint at {url}; attempt {attempt}")
            response = requests.post(url, json=data, timeout=(5, 300))
            if response.status_code in (502, 503) and attempt < 3:
                sleep(attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            prediction = payload.get("prediction")
            if not isinstance(prediction, dict):
                raise ValueError("PINES response is missing prediction")
            score = prediction.get("score")
            label = prediction.get("label")
            model_name = payload.get("model")
            threshold = payload.get("classification_threshold")
            if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise ValueError("PINES response has an invalid score")
            if label is None:
                raise ValueError("PINES response is missing label")
            if not isinstance(model_name, str) or not model_name.strip():
                raise ValueError("PINES response is missing model")
            if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                raise ValueError("PINES response has an invalid classification_threshold")
            is_negative = label == 0 or str(label).upper() in {"0", "LABEL_0"}
            positive_score = 1 - float(score) if is_negative else float(score)
            return positive_score, str(label), model_name, float(threshold)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 3:
                sleep(attempt)
                continue
            raise
    raise RuntimeError("PINES prediction failed") from last_error


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

    thresholds = set()
    models = set()
    for note in note_dicts:
        text_id = note["text_id"]
        if force_update or get_note_prediction_from_db(project_engine, text_id) is None:
            logger.info(f"Predicting for note: {text_id}")
            prediction, label, model_name, clf_threshold = get_prediction(
                pines_url, note["text"]
            )
            thresholds.add(clf_threshold)
            models.add(model_name)
            insert_pines_prediction(
                project_engine,
                text_id=text_id,
                patient_id=note["patient_id"],
                text_date=note["text_date"],
                predicted_score=prediction,
                predicted_label=label,
                model_name=model_name,
                classification_threshold=clf_threshold,
                report_type=note["text_tag_3"],
                document_type=note["text_tag_1"],
            )

    if len(thresholds) > 1 or len(models) > 1:
        raise ValueError("PINES returned inconsistent model metadata for one patient")
    return next(iter(thresholds), None)


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
