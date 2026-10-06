"""Patient completion after optional LLM filtering."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationPrediction
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
            .join(Note, Note.id == Annotation.note_id)
            .outerjoin(
                AnnotationPrediction,
                (AnnotationPrediction.annotation_id == Annotation.id)
                & (AnnotationPrediction.predictor_config_id == config.id),
            )
            .where(
                Annotation.project_id == project_id,
                Annotation.patient_id.in_(patient_ids),
                Annotation.review_excluded.is_(False),
                Note.deleted_at.is_(None),
            )
        )
    ).all()
    eligible: dict[str, bool] = {}
    for annotation, prediction in rows:
        negative = (
            prediction is not None
            and prediction.predicted_label == 0
            and not annotation.manual_review_override
            and annotation.reviewed_by is None
        )
        eligible[annotation.patient_id] = eligible.get(annotation.patient_id, True) and negative

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
        patient.status = PatientStatus.REVIEWED
        patient.review_source = "llm"
        patient.review_reason = "all_keyword_predictions_negative"
        patient.reviewed_by = None
        patient.reviewed_at = now_utc()
        patient.updated_at = now_utc()
        session.add(patient)