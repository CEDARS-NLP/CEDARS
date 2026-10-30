"""Tests for pipeline eval calibration metrics."""



from tests.test_pipeline_api import EVENT_CONFIG_BODY, create_project, register_and_login
from tests.test_pipeline_orchestration import _seed_patients


async def _setup_run_with_annotations(app, client, reviewed=True):
    """Create a project, seed patients, run sample, inject reviewed annotations."""
    from app.annotations.models import Annotation
    from app.dependencies import get_project_db_session
    from app.pipeline.models import PatientTask, PatientTaskStatus, PipelineRun, PipelineRunStatus
    from app.production.models import NotePrediction, ProductionRun

    await register_and_login(client)
    pid = await create_project(client)
    await _seed_patients(app, pid, count=4)
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
    async for session in app.dependency_overrides[get_project_db_session]():
        run = await session.get(PipelineRun, run_id)
        run.status = PipelineRunStatus.COMPLETED
        session.add(run)
        production_run = ProductionRun(project_id=pid, status="completed", config_snapshot={})
        session.add(production_run)
        await session.flush()

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

        from app.connectors.models import Note, Patient
        from app.projects.models import Project

        project = await session.get(Project, pid)

        for i, task in enumerate(tasks[:4]):
            task.status = PatientTaskStatus.COMPLETED
            session.add(task)

            note = (
                await session.execute(
                    select(Note).where(Note.patient_id == task.patient_id).limit(1)
                )
            ).scalars().first()

            pred_label, score, _, review_status = predictions[i]
            prediction = NotePrediction(
                project_id=pid,
                run_id=production_run.id,
                text_id=note.text_id,
                patient_id=note.patient_id_ext,
                patient_uuid=task.patient_id,
                note_uuid=note.id,
                status="succeeded",
                label=pred_label,
                score=score,
                reasoning="Calibration fixture",
                evidence_spans=[],
            )
            session.add(prediction)
            await session.flush()
            token_start = note.text.index("troponin")
            ann = Annotation(
                project_id=pid,
                patient_id=note.patient_id_ext,
                patient_uuid=task.patient_id,
                note_uuid=note.id,
                text_id=note.text_id,
                text_date=note.note_date.date(),
                sentence=note.text,
                token="troponin",
                isNegated=False,
                note_start_index=token_start,
                note_end_index=token_start + len("troponin"),
                sentence_number=0,
                sentence_start=0,
                sentence_end=len(note.text),
                pipeline_run_id=run_id,
                patient_task_id=task.id,
                production_run_id=production_run.id,
                prediction_id=prediction.id,
                status="R" if reviewed else "U",
                review_reason=(
                    "human_event" if review_status == "confirmed" else "human_negative"
                ) if reviewed else None,
                reviewed_by=project.owner_id if reviewed else None,
                actor_type="human" if reviewed else None,
            )
            session.add(ann)
            await session.flush()
            if reviewed and review_status == "confirmed":
                patient = await session.get(Patient, task.patient_id)
                patient.event_date = note.note_date.date()
                patient.event_annotation_id = ann.annotation_id
                patient.event_reviewer = project.owner_id
                session.add(patient)

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
