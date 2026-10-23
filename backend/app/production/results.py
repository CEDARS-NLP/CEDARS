"""Refresh the patient-level production RESULTS projection."""

from collections import Counter

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.models import Annotation
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.production.models import (
    NotePrediction,
    ProductionResult,
    ProductionRun,
    ProductionState,
)


async def refresh_patient_result(
    db: AsyncSession,
    project_id: str,
    patient_uuid: str,
) -> ProductionResult | None:
    """Rebuild one RESULTS row from source records and canonical patient state."""
    patient = (
        await db.execute(
            select(Patient).where(
                col(Patient.id) == patient_uuid,
                col(Patient.project_id) == project_id,
                col(Patient.deleted_at).is_(None),
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        return None

    result = (
        await db.execute(
            select(ProductionResult).where(
                col(ProductionResult.project_id) == project_id,
                col(ProductionResult.patient_uuid) == patient_uuid,
            )
        )
    ).scalar_one_or_none()
    if result is None:
        result = ProductionResult(
            project_id=project_id,
            patient_uuid=patient.id,
            patient_id=patient.patient_id_ext,
        )
        db.add(result)

    notes = (
        (
            await db.execute(
                select(Note)
                .where(
                    col(Note.project_id) == project_id,
                    col(Note.patient_id) == patient.id,
                    col(Note.deleted_at).is_(None),
                )
                .order_by(col(Note.note_date), col(Note.text_id))
            )
        )
        .scalars()
        .all()
    )
    annotations = (
        (
            await db.execute(
                select(Annotation)
                .where(
                    col(Annotation.project_id) == project_id,
                    col(Annotation.patient_id) == patient.patient_id_ext,
                )
                .order_by(
                    col(Annotation.text_date),
                    col(Annotation.text_id),
                    col(Annotation.note_start_index),
                )
            )
        )
        .scalars()
        .all()
    )

    state = await db.get(ProductionState, project_id)
    run = (
        await db.get(ProductionRun, state.active_run_id) if state and state.active_run_id else None
    )
    predictions_stmt = select(NotePrediction).where(
        col(NotePrediction.project_id) == project_id,
        col(NotePrediction.patient_uuid) == patient_uuid,
    )
    if state and state.active_run_id:
        predictions_stmt = predictions_stmt.where(col(NotePrediction.run_id) == state.active_run_id)
    else:
        predictions_stmt = predictions_stmt.where(col(NotePrediction.run_id) == "")
    predictions = (await db.execute(predictions_stmt)).scalars().all()

    note_by_text_id = {note.text_id: note for note in notes}
    statuses = Counter(prediction.status for prediction in predictions)
    notes_total = len(notes)
    notes_failed = statuses["failed"]
    annotations_by_status = Counter(annotation.status for annotation in annotations)
    reviewed_annotations = [
        annotation for annotation in annotations if annotation.status in {"R", "S"}
    ]
    reviewed_text_ids = {annotation.text_id for annotation in reviewed_annotations}
    reason_counts = Counter(
        annotation.review_reason for annotation in annotations if annotation.review_reason
    )

    if predictions:
        processing_status = next(
            (status for status in ("failed", "processing", "queued") if statuses[status]),
            "completed",
        )
    elif run and run.status in {"queued", "processing", "failed", "cancelled"}:
        processing_status = run.status
    else:
        processing_status = "completed" if annotations or not notes else "queued"

    if patient.reviewed_at:
        review_status = "reviewed"
    elif annotations_by_status["U"]:
        review_status = "pending"
    else:
        review_status = "completed"

    scored_predictions = [prediction for prediction in predictions if prediction.score is not None]
    best_prediction = (
        max(
            scored_predictions,
            key=lambda prediction: (
                prediction.score if prediction.score is not None else float("-inf")
            ),
        )
        if scored_predictions
        else None
    )
    best_note = note_by_text_id.get(best_prediction.text_id) if best_prediction else None
    reviewers = [annotation.reviewed_by for annotation in annotations if annotation.reviewed_by]
    comments = "\n".join(
        annotation.reviewer_notes.strip()
        for annotation in annotations
        if annotation.reviewer_notes and annotation.reviewer_notes.strip()
    )
    index_no = (
        await db.execute(
            select(func.count())
            .select_from(Patient)
            .where(col(Patient.project_id) == project_id, col(Patient.deleted_at).is_(None))
            .where(
                or_(
                    col(Patient.created_at) < patient.created_at,
                    and_(
                        col(Patient.created_at) == patient.created_at,
                        col(Patient.id) <= patient.id,
                    ),
                )
            )
        )
    ).scalar_one()

    result.patient_id = patient.patient_id_ext
    result.processing_status = processing_status
    result.review_status = review_status
    result.review_type = patient.review_type
    result.notes_total = notes_total
    result.notes_processed = statuses["succeeded"]
    if not predictions and processing_status == "completed":
        result.notes_processed = notes_total
    result.notes_failed = notes_failed
    result.annotations_total = len(annotations)
    result.annotations_pending = annotations_by_status["U"]
    result.annotations_reviewed = annotations_by_status["R"]
    result.annotations_skipped = annotations_by_status["S"]
    result.reason_counts = dict(reason_counts)
    result.failure_count = notes_failed
    result.comments = comments or None
    result.event_date = patient.event_date
    result.event_annotation_id = patient.event_annotation_id
    result.event_information = (
        {
            "event_date": patient.event_date.isoformat(),
            "annotation_id": patient.event_annotation_id,
            "reviewer": patient.event_reviewer,
        }
        if patient.event_date and patient.event_annotation_id
        else None
    )
    result.index_no = index_no
    result.first_note_date = notes[0].note_date if notes else None
    result.last_note_date = notes[-1].note_date if notes else None
    result.max_score = best_prediction.score if best_prediction else None
    result.max_score_note_date = best_note.note_date if best_note else None
    result.max_score_note_id = best_prediction.text_id if best_prediction else None
    result.reviewer = (
        patient.event_reviewer or patient.reviewed_by or (reviewers[-1] if reviewers else None)
    )
    result.reviewed_notes = len(reviewed_text_ids)
    result.reviewed_sentences = len(reviewed_annotations)
    result.total_notes = notes_total
    result.total_sentences = len(annotations)
    result.last_error = (
        "; ".join(
            prediction.error
            for prediction in predictions
            if prediction.status == "failed" and prediction.error
        )
        or None
    )
    result.last_updated_at = now_utc()
    return result


async def refresh_project_results(
    db: AsyncSession,
    project_id: str,
) -> list[ProductionResult]:
    """Refresh the RESULTS projection for each active patient in a project."""
    patients = (
        (
            await db.execute(
                select(col(Patient.id))
                .where(col(Patient.project_id) == project_id, col(Patient.deleted_at).is_(None))
                .order_by(col(Patient.created_at), col(Patient.id))
            )
        )
        .scalars()
        .all()
    )
    results = []
    for patient_uuid in patients:
        result = await refresh_patient_result(db, project_id, patient_uuid)
        if result is not None:
            results.append(result)
    return results
