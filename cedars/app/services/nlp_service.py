"""NLP orchestration service."""
from uuid import uuid4

from rq import Callback, Retry

from .. import queues, tasks
from ..database import get_current_project_engine
from ..database.db_query import get_search_query_details
from ..database.db_search import get_patient_ids, get_pines_status_counts, get_total_counts
from ..database.db_tasks import add_task
from ..database.db_updates import initialize_patient_pines_status
from ..database.project_table_creation import Patients, Task


def run_nlp(project_id: str, username: str, patient_ids=None) -> int:
    """Enqueue an NLP job per patient; returns the number dispatched."""
    project_engine = get_current_project_engine()
    query = get_search_query_details(project_engine)
    query_id = query.get("query_id")
    patient_ids = list(patient_ids) if patient_ids is not None else get_patient_ids(project_engine)
    if query_id is not None and query.get("apply_pines", False):
        initialize_patient_pines_status(project_engine, patient_ids, query_id)
    for patient in patient_ids:
        job_id = f"spacy:{project_id}:{query_id}:{uuid4().hex}:{patient}"
        add_task(project_engine, {
            "job_id": job_id,
            "name": "nlp_processor",
            "user_id": username,
            "complete": False,
            "progress": 0,
        })
        queues.get_task_queue(project_id).enqueue(
            tasks.nlp_task,
            args=(project_id, patient, query_id),
            job_id=job_id,
            description=f"Processing patient {patient} with spacy",
            retry=Retry(max=3),
            on_success=Callback(tasks.on_nlp_success),
            on_failure=Callback(tasks.on_nlp_failure),
            kwargs={
                "user": username,
                "job_id": job_id,
                "description": f"Processing patient {patient} with spacy",
            },
        )
    return len(patient_ids)


def nlp_status() -> dict:
    """Return per-project NLP progress based on the project's Task table."""
    project_engine = get_current_project_engine()
    total_patients = get_total_counts(project_engine, Patients)
    in_progress = get_total_counts(project_engine, Task, complete=False)
    completed = get_total_counts(project_engine, Task, complete=True)
    pines = get_pines_status_counts(project_engine)
    return {
        "total_patients": total_patients,
        "tasks_in_progress": in_progress,
        "tasks_completed": completed,
        # The Task table has no `failed` column (see db_tasks.py) - a failed
        # job is recorded as complete=True with progress left at 0.
        "tasks_failed": get_total_counts(project_engine, Task, complete=True, progress=0),
        "pines_pending": pines["pending"],
        "pines_running": pines["running"],
        "pines_succeeded": pines["succeeded"],
        "pines_failed": pines["failed"],
    }

