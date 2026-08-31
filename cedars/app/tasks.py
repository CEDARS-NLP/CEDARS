"""Project-scoped wrappers for background (RQ) jobs.

Enqueued jobs must bind the correct project database before touching the data
layer. These wrappers set the project context (a contextvar) for the duration of
the call, then delegate to the existing, unchanged business logic.

spaCy is imported lazily inside the task so that the web process and the job
*producer* never load the (heavy) NLP model — only the worker executing the job
does.
"""
from contextlib import contextmanager

from .database import (get_current_project_engine, reset_current_project_db,
                       set_current_project_db)
from .database.external_services import report_failure, report_success


@contextmanager
def project_scope(project_id):
    """Bind the current context to ``project_id``'s database for a job."""
    token = set_current_project_db(project_id)
    try:
        yield
    finally:
        reset_current_project_db(token)


def nlp_task(project_id, patient_id, **kwargs):
    """RQ task: run the spaCy keyword/negation pipeline for one patient."""
    from .nlpprocessor import NlpProcessor  # lazy import keeps spaCy out of the web process
    with project_scope(project_id):
        NlpProcessor().automatic_nlp_processor(patient_id, **kwargs)


def on_nlp_success(job, connection, result, *args, **kwargs):
    """RQ success callback: mark the task complete within its project scope."""
    with project_scope(job.args[0]):
        report_success(get_current_project_engine(), job)


def on_nlp_failure(job, connection, exc_type, exc_value, traceback):
    """RQ failure callback: record the failure within its project scope."""
    with project_scope(job.args[0]):
        report_failure(get_current_project_engine(), job)

