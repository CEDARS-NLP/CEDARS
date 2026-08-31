"""NLP orchestration service.

Ports the enqueue logic from the original Flask ``ops.do_nlp_processing`` and the
status views (``queue_stats`` / ``job_status``). The Superbio/EC2 spin-down
branch is dropped; the self-hosted PINES path is preserved (the worker checks
``tag_query.nlp_apply`` when processing). Job IDs are namespaced by project so
they never collide across projects on the shared Redis instance.
"""
from rq import Callback, Retry

from .. import queues, tasks
from ..database import get_current_project_engine
from ..database.db_search import get_patient_ids, get_total_counts
from ..database.db_tasks import add_task
from ..database.project_table_creation import Patients, Task


def run_nlp(project_id: str, username: str) -> int:
    """Enqueue an NLP job per patient; returns the number dispatched."""
    project_engine = get_current_project_engine()
    patient_ids = get_patient_ids(project_engine)
    for patient in patient_ids:
        job_id = f"spacy:{project_id}:{patient}"
        add_task(project_engine, {
            "job_id": job_id,
            "name": "nlp_processor",
            "user_id": username,
            "complete": False,
            "progress": 0,
        })
        queues.task_queue.enqueue(
            tasks.nlp_task,
            args=(project_id, patient),
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
    return {
        "total_patients": total_patients,
        "tasks_in_progress": in_progress,
        "tasks_completed": completed,
        # The Task table has no `failed` column (see db_tasks.py) - a failed
        # job is recorded as complete=True with progress left at 0.
        "tasks_failed": get_total_counts(project_engine, Task, complete=True, progress=0),
    }

