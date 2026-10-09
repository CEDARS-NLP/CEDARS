"""Patient completion after optional LLM filtering."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.predictors.models import PredictorConfig, PredictorType


async def complete_negative_llm_patients(
    session: AsyncSession, project_id: str, patient_ids: list[str], config: PredictorConfig,
) -> None:
    if config.predictor_type != PredictorType.LLM or not patient_ids:
        return

    await session.flush()
    rows = (
        await session.execute(
            select(Annotation, AnnotationPrediction)
            .join(Note, col(Note.id) == col(Annotation.note_id))
            .outerjoin(
                AnnotationPrediction,
                (col(AnnotationPrediction.annotation_id) == col(Annotation.id))
                & (col(AnnotationPrediction.predictor_config_id) == config.id),
            )
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id).in_(patient_ids),
                col(Annotation.review_excluded).is_(False),
                col(Note.deleted_at).is_(None),
            )
        )
    ).all()
    eligible: dict[str, bool] = {}
    human_reviewer: dict[str, str] = {}
    for annotation, prediction in rows:
        human_done = annotation.review_status != ReviewStatus.UNREVIEWED
        negative = (
            prediction is not None
            and prediction.predicted_label == 0
            and not annotation.manual_review_override
            and not human_done
        )
        if human_done and annotation.reviewed_by:
            human_reviewer[annotation.patient_id] = annotation.reviewed_by
        eligible[annotation.patient_id] = (
            eligible.get(annotation.patient_id, True) and (negative or human_done)
        )

    for patient_id, all_negative in eligible.items():
        patient = await session.get(Patient, patient_id)
        if patient is None or patient.review_source == "human" or patient.locked_by is not None:
            continue
        if not all_negative:
            if patient.review_source == "llm":
                patient.status = PatientStatus.NLP_COMPLETE
                patient.review_source = None
                patient.review_reason = None
                patient.reviewed_by = None
                patient.reviewed_at = None
                patient.updated_at = now_utc()
                session.add(patient)
            continue
        # Annotations a person already reviewed plus annotations the predictor ruled out:
        # nobody is left to review, so a human review closes the patient.
        reviewer = human_reviewer.get(patient_id)
        patient.status = PatientStatus.REVIEWED
        patient.review_source = "human" if reviewer else "llm"
        patient.review_reason = "manual_review" if reviewer else "all_keyword_predictions_negative"
        patient.reviewed_by = reviewer
        patient.reviewed_at = now_utc()
        patient.updated_at = now_utc()
        session.add(patient)
