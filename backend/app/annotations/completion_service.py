"""Compatibility adapter for production-owned patient completion."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import Patient
from app.predictors.models import PredictorConfig, PredictorType
from app.production.models import ProductionRun, ProductionState
from app.production.service import _patient_completion


async def complete_negative_llm_patients(
    session: AsyncSession, project_id: str, patient_ids: list[str], config: PredictorConfig,
) -> None:
    """Refresh completion through the active production run, never legacy predictions."""
    if config.predictor_type != PredictorType.LLM or not patient_ids:
        return

    state = await session.get(ProductionState, project_id)
    if state is None or state.active_run_id is None:
        return
    run = await session.get(ProductionRun, state.active_run_id)
    if run is None or run.project_id != project_id:
        return

    patients = await session.scalars(
        select(Patient).where(
            Patient.project_id == project_id,
            Patient.id.in_(patient_ids),
        )
    )
    for patient in patients:
        await _patient_completion(session, run, patient)
