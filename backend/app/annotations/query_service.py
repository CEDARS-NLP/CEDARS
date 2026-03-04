"""Query service: annotation lookups, listing, stats, context."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.connectors.models import Note, Patient
from app.nlp.models import Sentence

logger = logging.getLogger(__name__)


async def get_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
) -> Annotation | None:
    stmt = select(Annotation).where(
        Annotation.id == annotation_id,
        Annotation.project_id == project_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_annotations(
    session: AsyncSession,
    project_id: str,
    status: str | None = None,
    patient_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Annotation]:
    """List annotations with optional filtering."""
    stmt = select(Annotation).where(Annotation.project_id == project_id)

    if status:
        stmt = stmt.where(Annotation.review_status == status)
    if patient_id:
        stmt = stmt.where(Annotation.patient_id == patient_id)

    stmt = stmt.order_by(Annotation.created_at).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_next_unreviewed(
    session: AsyncSession,
    project_id: str,
    patient_id: str | None = None,
) -> Annotation | None:
    """Get the next unreviewed annotation for review."""
    stmt = select(Annotation).where(
        Annotation.project_id == project_id,
        Annotation.review_status == ReviewStatus.UNREVIEWED,
    )
    if patient_id:
        stmt = stmt.where(Annotation.patient_id == patient_id)
    stmt = stmt.order_by(Annotation.created_at).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_annotation_stats(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Get annotation review statistics for the project."""
    base = select(func.count()).select_from(Annotation).where(
        Annotation.project_id == project_id
    )

    total = (await session.execute(base)).scalar() or 0
    unreviewed = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.UNREVIEWED)
        )
    ).scalar() or 0
    reviewed = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.REVIEWED)
        )
    ).scalar() or 0
    skipped = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.SKIPPED)
        )
    ).scalar() or 0
    events_found = (
        await session.execute(
            base.where(Annotation.event_date.isnot(None))
        )
    ).scalar() or 0

    return {
        "total": total,
        "unreviewed": unreviewed,
        "reviewed": reviewed,
        "skipped": skipped,
        "events_found": events_found,
        "is_complete": total > 0 and unreviewed == 0,
    }


async def get_note_context(
    session: AsyncSession,
    note_id: str,
) -> dict | None:
    """Get full note text and all sentences for annotation context display."""
    note = (await session.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
    if not note:
        return None

    patient = (
        await session.execute(select(Patient).where(Patient.id == note.patient_id))
    ).scalar_one_or_none()

    sentences = (
        await session.execute(
            select(Sentence)
            .where(Sentence.note_id == note_id)
            .order_by(Sentence.sentence_number)
        )
    ).scalars().all()

    return {
        "note_id": note.id,
        "patient_id": note.patient_id,
        "patient_id_ext": patient.patient_id_ext if patient else note.patient_id,
        "text": note.text,
        "text_id": note.text_id,
        "note_date": note.note_date.isoformat() if note.note_date else None,
        "sentences": [
            {
                "id": s.id,
                "text": s.text,
                "start_pos": s.start_pos,
                "end_pos": s.end_pos,
                "is_target": s.is_target,
                "is_negated": s.is_negated,
                "matched_tokens": s.matched_tokens,
            }
            for s in sentences
        ],
    }
