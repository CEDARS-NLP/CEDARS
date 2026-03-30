"""Tests for pipeline eval calibration metrics."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.test_pipeline_api import EVENT_CONFIG_BODY, create_project, register_and_login
from tests.test_pipeline_orchestration import _seed_patients


async def _setup_run_with_annotations(app, client, reviewed=True):
    """Create a project, seed patients, run sample, inject reviewed annotations."""
    from app.annotations.models import Annotation, ReviewStatus
    from app.common.database import get_session
    from app.pipeline.models import PatientTask, PatientTaskStatus, PipelineRun, PipelineRunStatus

    await register_and_login(client)
    pid = await create_project(client)
    patient_ids = await _seed_patients(app, pid, count=4)
    eid_resp = await client.post(
        f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY,
    )
    eid = eid_resp.json()["id"]

    # Dispatch a sample run
    run_resp = await client.post(
        f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
        json={"sample_size": 4},
    )
    run_id = run_resp.json()["id"]

    # Simulate completed tasks with annotations
    async for session in app.dependency_overrides[get_session]():
        run = await session.get(PipelineRun, run_id)
        run.status = PipelineRunStatus.COMPLETED
        session.add(run)

        from sqlalchemy import select
        stmt = select(PatientTask).where(PatientTask.pipeline_run_id == run_id)
        result = await session.execute(stmt)
        tasks = list(result.scalars().all())

        # TP: predicted positive, reviewer confirms
        # FP: predicted positive, reviewer rejects
        # FN: predicted negative, reviewer says positive (marks as confirmed)
        # TN: predicted negative, reviewer rejects (agrees negative)
        predictions = [
            (1, 0.9, "positive", "confirmed"),  # TP
            (1, 0.8, "positive", "rejected"),    # FP
            (0, 0.3, "negative", "confirmed"),   # FN (reviewer overrides)
            (0, 0.2, "negative", "rejected"),    # TN (reviewer agrees negative)
        ]

        for i, task in enumerate(tasks[:4]):
            task.status = PatientTaskStatus.COMPLETED
            session.add(task)

            pred_label, score, _, review_status = predictions[i]
            ann = Annotation(
                project_id=pid,
                patient_id=task.patient_id,
                note_id="fake-note",
                sentence_id=f"fake-sent-{i}",
                sentence_text="test",
                predicted_score=score,
                predicted_label=pred_label,
                predictor_model="llama3",
                pipeline_run_id=run_id,
                patient_task_id=task.id,
                review_status=ReviewStatus(review_status) if reviewed else ReviewStatus.PENDING,
                reviewer_label="positive" if review_status == "confirmed" else "negative",
            )
            session.add(ann)

        await session.commit()

    return pid, run_id


class TestRunMetrics:
    async def test_compute_metrics(self, app, client):
        pid, run_id = await _setup_run_with_annotations(app, client)

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        # TP=1, FP=1, FN=1, TN=1
        assert data["true_positives"] == 1
        assert data["false_positives"] == 1
        assert data["false_negatives"] == 1
        assert data["true_negatives"] == 1
        assert data["precision"] == 0.5  # TP / (TP + FP) = 1/2
        assert data["recall"] == 0.5     # TP / (TP + FN) = 1/2
        assert data["total_reviewed"] == 4

    async def test_metrics_no_reviews_returns_zeros(self, app, client):
        pid, run_id = await _setup_run_with_annotations(app, client, reviewed=False)

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reviewed"] == 0
        assert data["precision"] is None
