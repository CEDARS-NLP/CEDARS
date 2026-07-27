"""Internal-process operations for the workflow (platform-admin only).

Ports v1's ops.py technical-admin routes: unlock patients, rebuild the results
table, re-run/reset NLP, drop project data, and surface queue/worker status.
"""

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationToken
from app.connectors.models import Note, NoteTag, Patient
from app.nlp.models import NotePrediction
from app.workflow import db_ops, service
from app.workflow.models import PatientReviewResult, ReviewSession

logger = logging.getLogger(__name__)


async def unlock_all_patients(session: AsyncSession, project_id: str) -> int:
    """Unlock every patient in the project (v1 ``remove_all_locked``)."""
    locked = (
        await session.execute(
            select(func.count(Patient.id)).where(
                Patient.project_id == project_id, Patient.locked_by.isnot(None)
            )
        )
    ).scalar_one()
    await db_ops.remove_all_locked(session, project_id)
    # Any dangling review sessions are no longer valid once patients are unlocked.
    await session.execute(
        delete(ReviewSession).where(ReviewSession.project_id == project_id)
    )
    await session.commit()
    return locked


async def unlock_patient(session: AsyncSession, project_id: str, patient_id: str) -> None:
    """Unlock a single patient (v1 ``unlock_patient``)."""
    await service.unlock_patient(session, project_id, patient_id)


async def rebuild_results(session: AsyncSession, project_id: str) -> int:
    """Rebuild the results table for every patient (v1 ``update_results_collection``)."""
    patient_ids = [
        row[0]
        for row in (
            await session.execute(
                select(Patient.id).where(
                    Patient.project_id == project_id, Patient.deleted_at.is_(None)
                )
            )
        ).all()
    ]
    for pid in patient_ids:
        await db_ops.upsert_patient_result(session, project_id, pid)
    await session.commit()
    return len(patient_ids)


async def rerun_nlp(session: AsyncSession, project_id: str, user_id: str) -> tuple[int, str]:
    """Clear annotations and re-run NLP for the whole project.

    Equivalent to saving a changed query: empties annotations, resets review
    state, then dispatches NLP again.
    """
    await db_ops.empty_annotations(session, project_id)
    await db_ops.reset_patient_reviewed(session, project_id)
    await session.execute(
        delete(ReviewSession).where(ReviewSession.project_id == project_id)
    )
    await session.commit()
    dispatched, mode, _ = await service.dispatch_nlp(session, project_id, user_id)
    return dispatched, mode


async def drop_project_data(session: AsyncSession, project_id: str) -> None:
    """Delete all workflow data for a project (patients, notes, annotations, results).

    Destructive reset so a project can be re-ingested from scratch. Leaves the
    project, its members, predictor configs, and saved queries intact.
    """
    ann_ids = select(Annotation.id).where(Annotation.project_id == project_id)
    note_ids = select(Note.id).where(Note.project_id == project_id)

    await session.execute(
        delete(AnnotationToken).where(AnnotationToken.annotation_id.in_(ann_ids))
    )
    await session.execute(delete(Annotation).where(Annotation.project_id == project_id))
    await session.execute(
        delete(NotePrediction).where(NotePrediction.project_id == project_id)
    )
    await session.execute(delete(NoteTag).where(NoteTag.note_id.in_(note_ids)))
    await session.execute(delete(ReviewSession).where(ReviewSession.project_id == project_id))
    await session.execute(
        delete(PatientReviewResult).where(PatientReviewResult.project_id == project_id)
    )
    await session.execute(delete(Note).where(Note.project_id == project_id))
    await session.execute(delete(Patient).where(Patient.project_id == project_id))
    await session.commit()
