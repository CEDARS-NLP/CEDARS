from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.annotations.models import Annotation, AnnotationPrediction
from app.common.database import get_session
from app.connectors.models import Patient
from app.pipeline.models import PipelineRun
from app.pipeline.service import compute_run_metrics
from app.production.classifier import NoteClassification
from app.production.models import NotePrediction, ProductionRun
from app.projects.models import Project
from tests.test_pipeline_api import EVENT_CONFIG_BODY, create_project, register_and_login
from tests.test_pipeline_orchestration import _seed_patients


async def test_legacy_full_run_uses_production_coordinator_and_requires_reset_confirmation(
    app, client
):
    await register_and_login(client)
    project_id = await create_project(client)
    await _seed_patients(app, project_id, count=2)

    event_response = await client.post(
        f"/api/v1/projects/{project_id}/pipeline/events",
        json=EVENT_CONFIG_BODY,
    )
    event_id = event_response.json()["id"]
    await client.post(
        f"/api/v1/projects/{project_id}/pipeline/events/{event_id}/commit",
        json={"confidence_threshold": 0.8},
    )

    full_response = await client.post(
        f"/api/v1/projects/{project_id}/pipeline/events/{event_id}/run-full",
    )
    assert full_response.status_code == 200
    legacy_run = full_response.json()
    assert legacy_run["config_snapshot"]["search_patterns"] == EVENT_CONFIG_BODY["search_patterns"]
    production_run_id = legacy_run["result_summary"]["production_run_id"]

    classification = NoteClassification(
        label=1,
        score=0.94,
        reasoning="The complete note supports the event.",
        evidence_spans=[],
        token_usage={"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
    )
    with patch(
        "app.production.service.classify_note",
        new=AsyncMock(return_value=classification),
    ):
        from app.jobs.pipeline import execute_pipeline_run

        stats = await execute_pipeline_run(legacy_run["id"], app.state.test_session_factory)

    assert stats["patients_completed"] == 2
    async for session in app.dependency_overrides[get_session]():
        production_run = await session.get(ProductionRun, production_run_id)
        legacy_run_row = await session.get(PipelineRun, legacy_run["id"])
        predictions = list(
            await session.scalars(
                select(NotePrediction).where(NotePrediction.run_id == production_run_id)
            )
        )
        annotations = list(
            await session.scalars(
                select(Annotation).where(Annotation.production_run_id == production_run_id)
            )
        )
        assert production_run.status == "completed"
        assert legacy_run_row.result_summary["production_run_id"] == production_run_id
        assert len(predictions) == 2
        assert all(prediction.status == "succeeded" for prediction in predictions)
        assert annotations
        assert all(annotation.text_id for annotation in annotations)
        assert list(await session.scalars(select(AnnotationPrediction))) == []

        annotation = annotations[0]
        patient = await session.get(Patient, annotation.patient_uuid)
        annotation.status = "R"
        annotation.review_reason = "human_event"
        await session.commit()
        stale_metrics = await compute_run_metrics(session, legacy_run["id"])
        assert stale_metrics["total_reviewed"] == 0

        project = await session.get(Project, project_id)
        patient.event_date = annotation.text_date
        patient.event_annotation_id = annotation.annotation_id
        patient.event_reviewer = project.owner_id
        await session.commit()
        canonical_metrics = await compute_run_metrics(session, legacy_run["id"])
        assert canonical_metrics["total_reviewed"] == 1
        assert canonical_metrics["true_positives"] == 1

    second_response = await client.post(
        f"/api/v1/projects/{project_id}/pipeline/events/{event_id}/run-full",
    )
    assert second_response.status_code == 400
    assert "confirm replacement" in second_response.json()["detail"].lower()
