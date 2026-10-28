from datetime import UTC, date, datetime

from httpx import AsyncClient
from sqlalchemy import select

from app.annotations.models import Annotation
from app.annotations.review_jobs import PatientReviewJob
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.models import SearchQuery
from app.production.models import (
    NotePrediction,
    ProductionRun,
    ProductionState,
)


async def _login_and_project(client: AsyncClient) -> tuple[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "production-review@example.com", "name": "Reviewer", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "production-review@example.com", "password": "secret123"},
    )
    response = await client.post(
        "/api/v1/projects", json={"name": "Manual review", "description": "test"}
    )
    assert response.status_code == 201
    return response.json()["id"], "production-review@example.com"


async def _seed_review_data(
    client: AsyncClient,
    *,
    skip_after_event: bool = True,
    exclude_negated: bool = False,
) -> tuple[str, str, list[int]]:
    project_id, email = await _login_and_project(client)
    app = client._transport.app
    annotation_ids = []
    async with app.state.test_session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        patient = Patient(project_id=project_id, patient_id_ext="P-REVIEW")
        session.add(patient)
        await session.flush()
        run = ProductionRun(
            project_id=project_id,
            created_by=user.id,
            status="completed",
            config_snapshot={"query": "finding"},
            total_notes=3,
            completed_notes=3,
        )
        session.add(run)
        await session.flush()
        session.add(ProductionState(project_id=project_id, active_run_id=run.id, generation=1))
        session.add(
            SearchQuery(
                project_id=project_id,
                query="finding",
                hide_duplicates=False,
                skip_after_event=skip_after_event,
                exclude_negated=exclude_negated,
            )
        )
        for index, note_date in enumerate((date(2026, 1, 10), date(2026, 1, 15), date(2026, 1, 20))):
            text_id = f"N-{index + 1}"
            text = f"Finding {index + 1} is documented."
            note = Note(
                project_id=project_id,
                patient_id=patient.id,
                patient_id_ext=patient.patient_id_ext,
                text_id=text_id,
                text=text,
                note_date=datetime.combine(note_date, datetime.min.time(), tzinfo=UTC),
            )
            session.add(note)
            await session.flush()
            prediction = NotePrediction(
                project_id=project_id,
                run_id=run.id,
                text_id=text_id,
                patient_id=patient.patient_id_ext,
                note_uuid=note.id,
                patient_uuid=patient.id,
                status="succeeded",
                label=1,
                score=0.91,
                reasoning="Evidence found.",
                evidence_spans=[{"start": 0, "end": 7, "text": "Finding"}],
            )
            session.add(prediction)
            annotation = Annotation(
                project_id=project_id,
                text_id=text_id,
                patient_id=patient.patient_id_ext,
                text_date=note_date,
                sentence=text,
                token="Finding",
                isNegated=False,
                note_start_index=0,
                note_end_index=7,
                sentence_number=0,
                sentence_start=0,
                sentence_end=len(text),
                patient_uuid=patient.id,
                note_uuid=note.id,
                production_run_id=run.id,
            )
            session.add(annotation)
            await session.flush()
            annotation_ids.append(annotation.annotation_id)
        await session.commit()
    return project_id, patient.id, annotation_ids


async def _patient_annotations(client: AsyncClient, project_id: str, patient_id: str):
    response = await client.get(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/annotations"
    )
    assert response.status_code == 200
    return response.json()


async def _navigate(client: AsyncClient, project_id: str, patient_id: str, action: str):
    return await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/navigate/{action}"
    )


async def test_patient_next_and_annotations_api_include_prediction_evidence(client):
    project_id, patient_id, _ = await _seed_review_data(client)

    claimed = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claimed.status_code == 200
    assert claimed.json()["patient_id"] == patient_id
    assert claimed.json()["current_annotation_id"] is not None
    assert claimed.json()["next_annotation_id"] is not None

    annotations = await _patient_annotations(client, project_id, patient_id)
    assert len(annotations) == 3
    assert annotations[0]["evidence_spans"] == [
        {"start": 0, "end": 7, "text": "Finding"}
    ]

    context = await client.get(
        f"/api/v1/projects/{project_id}/annotations/{annotations[0]['id']}/context"
    )
    assert context.status_code == 200
    assert context.json()["current_note_evidence"] == annotations[0]["evidence_spans"]


async def test_manual_event_replacement_recalculates_later_and_earlier_dates(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200
    first, second, third = await _patient_annotations(client, project_id, patient_id)

    first_event = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{first['id']}/review",
        json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
    )
    assert first_event.status_code == 200
    assert first_event.json()["skipped_count"] == 2

    moved = await _navigate(client, project_id, patient_id, "next_1")
    assert moved.status_code == 200
    assert moved.json()["current_annotation_id"] == second["id"]
    later = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{second['id']}/review",
        json={"event_date": "2026-01-15T00:00:00Z", "skip_after_event": True},
    )
    assert later.status_code == 200, later.text
    assert later.json()["skipped_count"] == 1

    app = client._transport.app
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        event_one = await session.get(Annotation, ids[0])
        event_two = await session.get(Annotation, ids[1])
        event_three = await session.get(Annotation, ids[2])
        assert patient.event_date == date(2026, 1, 15)
        assert patient.event_annotation_id == ids[1]
        assert event_one.review_reason == "human_event"
        assert event_two.review_reason == "human_event"
        assert event_three.review_reason == "event_date_skip"

    await _navigate(client, project_id, patient_id, "first_anno")
    earlier = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{first['id']}/review",
        json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
    )
    assert earlier.status_code == 200
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        event_two = await session.get(Annotation, ids[1])
        event_three = await session.get(Annotation, ids[2])
        assert patient.event_date == date(2026, 1, 10)
        assert patient.event_annotation_id == ids[0]
        assert event_two.review_reason == "human_event"
        assert event_three.review_reason == "event_date_skip"


async def test_event_skip_off_and_delete_reopen_transitions(client):
    project_id, patient_id, ids = await _seed_review_data(client, skip_after_event=False)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200
    annotations = await _patient_annotations(client, project_id, patient_id)
    event = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{annotations[0]['id']}/review",
        json={"event_date": "2026-01-10T00:00:00Z"},
    )
    assert event.status_code == 200
    assert event.json()["skipped_count"] == 0
    assert event.json()["current_annotation_id"] == str(ids[1])
    assert event.json()["next_annotation_id"] == str(ids[2])

    await _navigate(client, project_id, patient_id, "first_anno")
    deleted = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{annotations[0]['id']}/delete-event-date"
    )
    assert deleted.status_code == 200
    assert deleted.json()["annotation"]["event_date"] is None
    assert deleted.json()["annotation"]["review_status"] == "unreviewed"

    app = client._transport.app
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        first = await session.get(Annotation, ids[0])
        assert patient.event_annotation_id is None
        assert first.review_reason is None
        patient.status = PatientStatus.REVIEWED
        patient.locked_by = None
        await session.commit()

    reopened = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/reopen"
    )
    assert reopened.status_code == 200
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        assert patient.status == PatientStatus.REVIEWING
        assert patient.locked_by is None


async def test_manual_write_rejects_patient_locked_by_another_user(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200
    app = client._transport.app
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        other = User(
            email="other-reviewer@example.com",
            name="Other reviewer",
            password_hash="x",
        )
        session.add(other)
        await session.flush()
        patient.locked_by = other.id
        await session.commit()

    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/{ids[0]}/review", json={}
    )
    assert response.status_code == 409


async def test_note_context_hides_negated_but_keeps_duplicate_occurrence_spans(client):
    project_id, patient_id, ids = await _seed_review_data(client, exclude_negated=True)
    app = client._transport.app
    async with app.state.test_session_factory() as session:
        first = await session.get(Annotation, ids[0])
        second = await session.get(Annotation, ids[1])
        second.isNegated = True
        second.status = "R"
        second.review_reason = "negated"
        first_note = await session.get(Note, first.note_uuid)
        repeated_sentence = f" {first.sentence}"
        duplicate_start = len(first_note.text)
        first_note.text += repeated_sentence
        duplicate = Annotation(
            project_id=project_id,
            text_id=first.text_id,
            patient_id=first.patient_id,
            text_date=first.text_date,
            sentence=first.sentence,
            token=first.token,
            isNegated=False,
            note_start_index=duplicate_start + 1,
            note_end_index=duplicate_start + 1 + len(first.token),
            sentence_number=1,
            sentence_start=duplicate_start + 1,
            sentence_end=duplicate_start + 1 + len(first.sentence),
            patient_uuid=first.patient_uuid,
            note_uuid=first.note_uuid,
            production_run_id=first.production_run_id,
            status="R",
            review_reason="duplicate",
        )
        session.add(duplicate)
        await session.commit()

    negated_context = await client.get(
        f"/api/v1/projects/{project_id}/annotations/{ids[1]}/context"
    )
    assert negated_context.status_code == 200
    assert negated_context.json()["annotation_spans"] == []

    annotations = await _patient_annotations(client, project_id, patient_id)
    first_annotation = next(row for row in annotations if row["id"] == str(ids[0]))
    context = await client.get(
        f"/api/v1/projects/{project_id}/annotations/{first_annotation['id']}/context"
    )
    assert context.status_code == 200
    spans = context.json()["annotation_spans"]
    assert len(spans) == 2
    assert spans[0]["start"] != spans[1]["start"]


async def test_review_batch_keeps_lock_until_worker_applies_complete_batch(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    body = {
        "idempotency_key": "batch-complete-patient-1",
        "skip_after_event": True,
        "decisions": [
            {"annotation_id": str(annotation_id), "status": "reviewed", "event_date": None}
            for annotation_id in ids
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "queued"

    app = client._transport.app
    async with app.state.test_session_factory() as session:
        job = await session.get(PatientReviewJob, job_id)
        patient = await session.get(Patient, patient_id)
        assert job is not None and job.status == "queued"
        assert patient is not None and patient.locked_by is not None
        rows = [await session.get(Annotation, annotation_id) for annotation_id in ids]
        assert all(row.status == "U" for row in rows)

    next_patient = await client.get(
        f"/api/v1/projects/{project_id}/annotations/patient/next"
    )
    assert next_patient.status_code == 200
    assert next_patient.json()["patient_id"] is None
    assert next_patient.json()["pending_review_jobs"] == 1
    assert next_patient.json()["all_complete"] is False

    from app.jobs.review import execute_patient_review_job

    result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
    assert result["status"] == "completed"
    async with app.state.test_session_factory() as session:
        job = await session.get(PatientReviewJob, job_id)
        patient = await session.get(Patient, patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in ids]
        assert job.status == "completed"
        assert patient.locked_by is None
        assert patient.status == PatientStatus.REVIEWED
        assert all(row.status == "R" and row.review_reason == "human_negative" for row in rows)


async def test_review_batch_unlocks_after_third_worker_failure(client, monkeypatch):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json={
            "idempotency_key": "batch-fails-three-times",
            "decisions": [
                {"annotation_id": str(annotation_id), "status": "reviewed", "event_date": None}
                for annotation_id in ids
            ],
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    app = client._transport.app

    async def fail_apply(*_args, **_kwargs):
        raise RuntimeError("synthetic review write failure")

    async def enqueued(*_args, **_kwargs):
        return True

    monkeypatch.setattr("app.annotations.adjudication_service.apply_patient_review_job", fail_apply)
    monkeypatch.setattr("app.jobs.review.enqueue_review_job", enqueued)
    from app.jobs.review import execute_patient_review_job

    for expected_attempt in (1, 2, 3):
        result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
        assert result["attempt_count"] == expected_attempt

    async with app.state.test_session_factory() as session:
        job = await session.get(PatientReviewJob, job_id)
        patient = await session.get(Patient, patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in ids]
        assert job.status == "failed"
        assert job.attempt_count == 3
        assert job.last_error == "synthetic review write failure"
        assert patient.locked_by is None
        assert all(row.status == "U" for row in rows)


async def test_review_batch_accepts_out_of_order_snapshot(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    # Submit the snapshot in reverse order; the batch must apply by annotation id.
    body = {
        "idempotency_key": "batch-out-of-order",
        "skip_after_event": False,
        "decisions": [
            {"annotation_id": str(annotation_id), "status": "reviewed", "event_date": None}
            for annotation_id in reversed(ids)
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    from app.jobs.review import execute_patient_review_job

    app = client._transport.app
    result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
    assert result["status"] == "completed"
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in ids]
        assert patient.status == PatientStatus.REVIEWED
        assert all(row.status == "R" and row.review_reason == "human_negative" for row in rows)


async def test_review_batch_accepts_incomplete_snapshot(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    body = {
        "idempotency_key": "batch-incomplete",
        "skip_after_event": False,
        "decisions": [
            {"annotation_id": str(ids[0]), "status": "reviewed", "event_date": None},
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    from app.jobs.review import execute_patient_review_job

    app = client._transport.app
    result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
    assert result["status"] == "completed"
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in ids]
        assert patient.status == PatientStatus.REVIEWING
        assert rows[0].status == "R"
        assert rows[1].status == "U"
        assert rows[2].status == "U"


async def test_review_batch_records_note_review_type_and_results(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    body = {
        "idempotency_key": "batch-note-review-type",
        "skip_after_event": False,
        "decisions": [
            {"annotation_id": str(annotation_id), "status": "reviewed", "event_date": None}
            for annotation_id in ids
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    from app.jobs.review import execute_patient_review_job
    from app.production.models import ProductionResult

    app = client._transport.app
    result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
    assert result["status"] == "completed"
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        notes = (
            await session.execute(select(Note).where(Note.patient_id == patient_id))
        ).scalars().all()
        assert patient.review_type == "human"
        assert all(note.review_status == "reviewed" for note in notes)
        assert all(note.review_type == "human" for note in notes)
        production_result = await session.scalar(
            select(ProductionResult).where(ProductionResult.patient_uuid == patient_id)
        )
        assert production_result is not None
        assert production_result.review_type == "human"


async def test_review_batch_marks_llm_negative_note_reviewed(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    app = client._transport.app
    async with app.state.test_session_factory() as session:
        prediction = await session.scalar(
            select(NotePrediction).where(NotePrediction.text_id == "N-1")
        )
        prediction.label = 0
        session.add(prediction)
        await session.commit()

    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    body = {
        "idempotency_key": "batch-llm-negative",
        "skip_after_event": False,
        "decisions": [
            {"annotation_id": str(ids[1]), "status": "reviewed", "event_date": None},
            {"annotation_id": str(ids[2]), "status": "reviewed", "event_date": None},
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    from app.jobs.review import execute_patient_review_job

    result = await execute_patient_review_job(project_id, job_id, app.state.test_session_factory)
    assert result["status"] == "completed"
    async with app.state.test_session_factory() as session:
        patient = await session.get(Patient, patient_id)
        llm_note = await session.scalar(select(Note).where(Note.text_id == "N-1"))
        assert patient.status == PatientStatus.REVIEWED
        assert llm_note.review_status == "reviewed"
        assert llm_note.review_type == "llm"


async def test_review_batch_rejects_multiple_event_dates(client):
    project_id, patient_id, ids = await _seed_review_data(client)
    claim = await client.get(f"/api/v1/projects/{project_id}/annotations/patient/next")
    assert claim.status_code == 200

    # The frontend must collapse to a single event date; the API guards against
    # a batch that carries more than one so the ground truth stays unambiguous.
    body = {
        "idempotency_key": "batch-multiple-events",
        "skip_after_event": False,
        "decisions": [
            {"annotation_id": str(ids[0]), "status": "reviewed", "event_date": "2026-01-15"},
            {"annotation_id": str(ids[1]), "status": "reviewed", "event_date": "2026-02-15"},
        ],
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/annotations/patient/{patient_id}/review-batches",
        json=body,
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Review batch contains multiple event dates"
