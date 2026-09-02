'''
db_tasks.py

Background task/job bookkeeping for a project (mirrors mongo's TASK collection).
'''
from typing import List, Optional

from loguru import logger

from sqlalchemy import insert, select, update

from ..cedars_enums import log_function_call
from .db_session import session_scope
from .db_updates import set_patient_lock_status
from .project_table_creation import Task

logger.enable(__name__)


@log_function_call
def add_task(project_engine, task: dict) -> None:
    '''
    Creates or resets a task record keyed by job_id.

    Args:
        task (dict): keys matching the Task columns (job_id, name, user_id,
                     complete, progress).
    '''
    task = dict(task)
    task.setdefault("complete", False)
    task.setdefault("progress", 0)

    with session_scope(project_engine) as session:
        existing = session.execute(
            select(Task).where(Task.job_id == task["job_id"])
        ).scalar_one_or_none()

        if existing is None:
            session.execute(insert(Task).values(**task))
        else:
            session.execute(update(Task).where(Task.job_id == task["job_id"]).values(**task))


@log_function_call
def get_tasks_in_progress(project_engine) -> List[Task]:
    '''
    Every task that has not yet completed.
    '''
    with session_scope(project_engine) as session:
        return session.execute(select(Task).where(Task.complete == False)).scalars().all()  # noqa: E712


@log_function_call
def get_task(project_engine, job_id) -> Optional[Task]:
    '''
    A task by job_id, regardless of completion status, or None.
    '''
    with session_scope(project_engine) as session:
        return session.execute(select(Task).where(Task.job_id == job_id)).scalar_one_or_none()


@log_function_call
def get_task_in_progress(project_engine, job_id) -> Optional[Task]:
    '''
    A task by job_id, only if it has not yet completed, else None.
    '''
    with session_scope(project_engine) as session:
        return session.execute(
            select(Task).where(Task.job_id == job_id, Task.complete == False)  # noqa: E712
        ).scalar_one_or_none()


@log_function_call
def update_db_task_progress(project_engine, job_id, progress, failed=False) -> None:
    '''
    Updates a task's progress, marking it complete if finished or failed, and
    automatically unlocking the patient the task was working on.

    Note: unlike mongo, the Task table has no `failed` column - a failure is
    recorded as complete=True with progress left at its last value (0 for a
    fresh failure, per report_failure()).
    '''
    with session_scope(project_engine) as session:
        task = session.execute(select(Task).where(Task.job_id == job_id)).scalar_one_or_none()

        if task is None:
            # this might be the case if we have old messages in the queue
            logger.error(f"Task {job_id} not found in database.")
            return

        completed = progress >= 100 or failed
        session.execute(
            update(Task).where(Task.job_id == job_id)
            .values(progress=progress, complete=completed)
        )

    patient_id = job_id.rsplit(":", 1)[-1].strip()
    set_patient_lock_status(project_engine, patient_id, False)
