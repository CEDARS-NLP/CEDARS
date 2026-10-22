from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.annotations import adjudication_service, review_service
from app.annotations.adjudication_compat import ReviewStatus
from app.annotations.adjudication_handler import AdjudicationHandler, SentenceHighlighter
from app.annotations.models import Annotation
from app.annotations.review_state import ReviewStateStore
from app.connectors.models import Patient, PatientStatus
from app.nlp.models import SearchQuery
from app.production.models import NotePrediction, ProductionResult, ProductionRun, ProductionState


def _annotation(annotation_id, text_id, sentence, start, status="U", negated=False):
    return SimpleNamespace(
        annotation_id=annotation_id,
        text_id=text_id,
        sentence=sentence,
        status=status,
        isNegated=negated,
        text_date=date(2026, 1, 1),
        sentence_number=0,
        note_start_index=start,
        note_end_index=start + len(sentence),
    )


def test_handler_deduplicates_and_advances_with_reference_statuses():
    annotations = [
        _annotation(10, "N1", "Finding alpha", 0),
        _annotation(11, "N2", " finding ALPHA ", 8),
        _annotation(12, "N2", "Finding beta", 22),
    ]
    handler = AdjudicationHandler("P1")

    state, duplicates = handler.init_patient_data(annotations, hide_duplicates=True)

    assert state["annotation_ids"] == ["10", "12"]
    assert duplicates == ["11"]
    assert handler.get_curr_annotation_id() == "10"
    handler._adjudicate_annotation()
    assert handler.get_curr_annotation_id() == "12"
    assert state["review_statuses"] == [ReviewStatus.REVIEWED, ReviewStatus.UNREVIEWED]


def test_retained_negated_occurrence_is_highlighted_from_stored_offsets():
    note = SimpleNamespace(text="No finding alpha was seen.")
    annotation = _annotation(1, "N1", "no finding alpha was seen.", 3, negated=True)
    annotation.note_end_index = 16

    rendered = SentenceHighlighter().get_highlighted_sentence(
        annotation, note, [annotation]
    )

    assert rendered == "No <b><mark>finding alpha</mark></b> was seen."


async def test_review_cursor_cache_failure_falls_back_without_raising(monkeypatch):
    async def unavailable_pool(*args, **kwargs):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr("arq.create_pool", unavailable_pool)
    store = ReviewStateStore()

    assert await store.load("project", "user", "run") is None
    await store.save("project", "user", "run", 4, ["12", "13"], "12")
    assert adjudication_service._EXCLUDED_REASONS == {
        "llm_negative", "duplicate", "negated"
    }


async def test_review_service_forwards_skip_after_event_setting(monkeypatch):
    observed = {}

    async def apply_action(*args, **kwargs):
        observed.update(kwargs)
        return None

    monkeypatch.setattr(review_service, "apply_review_action", apply_action)

    await review_service.review_annotation(
        None, "project", "15", "reviewer", date(2026, 5, 2), False
    )

    assert observed["action"] == "event"
    assert observed["event_date"] == date(2026, 5, 2)
    assert observed["skip_after_event"] is False


async def test_explicit_skip_after_event_false_overrides_stored_settings():
    assert not await adjudication_service._skip_after_event_enabled(
        None, "project", False
    )


@pytest.fixture
async def manual_review(client):
    from tests.test_production_adjudication_api import _seed_review_data

    project_id, patient_id, annotation_ids = await _seed_review_data(client)
    return SimpleNamespace(
        project_id=project_id,
        patient_id=patient_id,
        ids=annotation_ids,
        base=f"/api/v1/projects/{project_id}/annotations",
        sessions=client._transport.app.state.test_session_factory,
    )


async def test_negative_completion_clears_lock_and_refreshes_results(client, manual_review):
    data = manual_review
    claim = await client.get(f"{data.base}/patient/next")
    assert claim.status_code == 200
    assert claim.json()["current_annotation_id"] == str(data.ids[0])

    for annotation_id in data.ids:
        response = await client.post(f"{data.base}/{annotation_id}/review", json={})
        assert response.status_code == 200, response.text

    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        result = await session.scalar(select(ProductionResult).where(
            ProductionResult.patient_uuid == data.patient_id
        ))
        assert patient.status == PatientStatus.REVIEWED
        assert patient.locked_by is None
        assert patient.locked_at is None
        assert patient.reviewed_at is not None
        assert patient.reviewed_by is not None
        assert patient.review_source == "human"
        assert result.review_status == "reviewed"
        assert result.reviewer == patient.reviewed_by
        assert result.annotations_reviewed == 3
        assert result.annotations_pending == 0
    claim = await client.get(f"{data.base}/patient/next")
    assert claim.json()["all_complete"] is True


async def test_coordinator_skip_advances_and_wraps_without_handler_extension(client, manual_review):
    data = manual_review
    moved = await client.post(f"{data.base}/patient/{data.patient_id}/navigate/last_anno")
    assert moved.status_code == 200
    skipped = await client.post(f"{data.base}/{data.ids[2]}/skip")
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["review_status"] == "skipped"
    cursor = await client.get(f"{data.base}/patient/{data.patient_id}/cursor")
    assert cursor.json()["current_annotation_id"] == str(data.ids[0])
    assert cursor.json()["next_annotation_id"] == str(data.ids[1])


async def test_event_api_later_then_earlier_recalculates_only_event_skips(client, manual_review):
    data = manual_review
    assert (await client.get(f"{data.base}/patient/next")).status_code == 200
    first = await client.post(
        f"{data.base}/{data.ids[0]}/review",
        json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
    )
    assert first.status_code == 200, first.text
    assert first.json()["skipped_count"] == 2
    moved = await client.post(f"{data.base}/patient/{data.patient_id}/navigate/next_1")
    assert moved.json()["current_annotation_id"] == str(data.ids[1])
    later = await client.post(
        f"{data.base}/{data.ids[1]}/review",
        json={"event_date": "2026-01-25T00:00:00Z", "skip_after_event": True},
    )
    assert later.status_code == 200, later.text
    assert later.json()["skipped_count"] == 0
    assert later.json()["current_annotation_id"] == str(data.ids[2])
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in data.ids]
        assert patient.event_date == date(2026, 1, 25)
        assert patient.event_annotation_id == data.ids[1]
        assert patient.reviewed_at is None
        assert rows[0].review_reason == rows[1].review_reason == "human_event"
        assert rows[2].status == "U"
        assert rows[2].skipped_by_event_annotation_id is None

    await client.post(f"{data.base}/patient/{data.patient_id}/navigate/first_anno")
    earlier = await client.post(
        f"{data.base}/{data.ids[0]}/review",
        json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
    )
    assert earlier.status_code == 200, earlier.text
    assert earlier.json()["skipped_count"] == 1
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        second = await session.get(Annotation, data.ids[1])
        third = await session.get(Annotation, data.ids[2])
        result = await session.scalar(select(ProductionResult).where(
            ProductionResult.patient_uuid == data.patient_id
        ))
        assert patient.event_annotation_id == data.ids[0]
        assert patient.status == PatientStatus.REVIEWED
        assert patient.locked_by is None
        assert second.status == "R"
        assert second.review_reason == "human_event"
        assert third.status == "S"
        assert third.skipped_by_event_annotation_id == data.ids[0]
        assert result.event_date == patient.event_date == date(2026, 1, 10)
        assert result.event_annotation_id == data.ids[0]
        assert result.review_status == "reviewed"


@pytest.mark.parametrize("exclude_earlier", [False, True])
async def test_event_api_counts_only_eligible_earlier_pending(
    client, manual_review, exclude_earlier
):
    data = manual_review
    if exclude_earlier:
        async with data.sessions() as session:
            first = await session.get(Annotation, data.ids[0])
            first.isNegated = True
            query = await session.scalar(select(SearchQuery).where(
                SearchQuery.project_id == data.project_id
            ))
            query.exclude_negated = True
            await session.commit()
    await client.post(f"{data.base}/patient/{data.patient_id}/navigate/last_anno")
    response = await client.post(
        f"{data.base}/{data.ids[2]}/review",
        json={"event_date": "2026-01-20T00:00:00Z", "skip_after_event": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["earlier_count"] == (1 if exclude_earlier else 2)
    assert response.json()["skipped_count"] == 0
    assert response.json()["current_annotation_id"] == str(data.ids[1 if exclude_earlier else 0])


async def test_delete_event_api_restores_event_skips_but_preserves_manual_skip(client, manual_review):
    data = manual_review
    await client.get(f"{data.base}/patient/next")
    assert (await client.post(f"{data.base}/{data.ids[0]}/skip")).status_code == 200
    event = await client.post(
        f"{data.base}/{data.ids[1]}/review",
        json={"event_date": "2026-01-15T00:00:00Z", "skip_after_event": True},
    )
    assert event.status_code == 200, event.text
    assert event.json()["skipped_count"] == 1
    deleted = await client.post(f"{data.base}/{data.ids[1]}/delete-event-date")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["reverted_count"] == 1
    assert deleted.json()["annotation"]["event_date"] is None
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in data.ids]
        assert [row.status for row in rows] == ["S", "U", "U"]
        assert all(row.review_reason is None for row in rows)
        assert patient.event_date is None
        assert patient.event_annotation_id is None
        assert patient.event_reviewer is None
        assert patient.status == PatientStatus.REVIEWING
        assert patient.reviewed_at is None
        result = await session.scalar(select(ProductionResult).where(
            ProductionResult.patient_uuid == data.patient_id
        ))
        assert result.event_date is None
        assert result.review_status == "pending"
        assert result.annotations_pending == 2
        assert result.annotations_skipped == 1
    cursor = await client.get(f"{data.base}/patient/{data.patient_id}/cursor")
    assert cursor.json()["current_annotation_id"] == str(data.ids[1])
    assert cursor.json()["next_annotation_id"] == str(data.ids[2])


async def test_reopen_event_api_preserves_decisions_and_refreshes_results(client, manual_review):
    data = manual_review
    await client.get(f"{data.base}/patient/next")
    event = await client.post(
        f"{data.base}/{data.ids[0]}/review",
        json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
    )
    assert event.status_code == 200
    reopened = await client.post(f"{data.base}/patient/{data.patient_id}/reopen")
    assert reopened.status_code == 200, reopened.text
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        rows = [await session.get(Annotation, annotation_id) for annotation_id in data.ids]
        assert patient.status == PatientStatus.REVIEWING
        assert patient.event_date == date(2026, 1, 10)
        assert patient.event_annotation_id == data.ids[0]
        assert patient.locked_by is None
        assert patient.reviewed_at is None
        assert [row.status for row in rows] == ["R", "S", "S"]
        result = await session.scalar(select(ProductionResult).where(
            ProductionResult.patient_uuid == data.patient_id
        ))
        assert result.event_annotation_id == data.ids[0]
        assert result.event_date == patient.event_date
        assert result.review_status != "reviewed"


@pytest.mark.parametrize("prediction_status", ["queued", "processing", "failed", "missing"])
async def test_get_next_blocks_patient_until_all_predictions_succeed(
    client, manual_review, prediction_status
):
    data = manual_review
    async with data.sessions() as session:
        prediction = await session.scalar(select(NotePrediction).where(
            NotePrediction.project_id == data.project_id, NotePrediction.text_id == "N-3"
        ))
        run = await session.get(ProductionRun, prediction.run_id)
        run.config_snapshot = {"llm_config": {"provider": "openai", "model": "test"}}
        if prediction_status == "missing":
            await session.delete(prediction)
        else:
            prediction.status = prediction_status
        await session.commit()
    next_annotation = await client.get(f"{data.base}/next")
    assert next_annotation.status_code == 200
    assert next_annotation.json() is None
    claimed = await client.get(f"{data.base}/patient/next")
    assert claimed.status_code == 200
    assert claimed.json()["patient_id"] is None
    assert claimed.json()["all_complete"] is False
    async with data.sessions() as session:
        assert (await session.get(Patient, data.patient_id)).locked_by is None


async def test_get_next_blocks_patient_while_production_search_is_unfinished(client, manual_review):
    data = manual_review
    async with data.sessions() as session:
        state = await session.get(ProductionState, data.project_id)
        run = await session.get(ProductionRun, state.active_run_id)
        run.status = "running"
        run.progress_metadata = {"scanned_note_match_counts": {"N-1": 1}}
        await session.commit()
    assert (await client.get(f"{data.base}/next")).json() is None
    response = await client.get(f"{data.base}/patient/next")
    assert response.json()["patient_id"] is None
    assert response.json()["all_complete"] is False


@pytest.mark.parametrize("prediction_status", ["queued", "failed"])
async def test_completion_requires_successful_predictions_even_without_pending_annotations(
    client, manual_review, prediction_status
):
    data = manual_review
    async with data.sessions() as session:
        prediction = await session.scalar(select(NotePrediction).where(
            NotePrediction.project_id == data.project_id, NotePrediction.text_id == "N-3"
        ))
        prediction.status = prediction_status
        await session.commit()
    for annotation_id in data.ids:
        response = await client.post(f"{data.base}/{annotation_id}/review", json={})
        assert response.status_code == 200, response.text
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        result = await session.scalar(select(ProductionResult).where(
            ProductionResult.patient_uuid == data.patient_id
        ))
        assert patient.status != PatientStatus.REVIEWED
        assert patient.reviewed_at is None
        assert result.review_status != "reviewed"
        assert result.processing_status == prediction_status
    response = await client.get(f"{data.base}/patient/next")
    assert response.json()["patient_id"] is None
    assert response.json()["all_complete"] is False


async def test_keyword_only_patient_is_claimable_without_predictions(client, manual_review):
    data = manual_review
    async with data.sessions() as session:
        predictions = await session.scalars(select(NotePrediction).where(
            NotePrediction.project_id == data.project_id
        ))
        for prediction in predictions:
            await session.delete(prediction)
        await session.commit()
    assert (await client.get(f"{data.base}/next")).json()["id"] == str(data.ids[0])
    response = await client.get(f"{data.base}/patient/next")
    assert response.json()["patient_id"] == data.patient_id


@pytest.mark.parametrize("run_status", ["running", "failed", "cancelled"])
async def test_get_next_allows_successful_patient_after_search_finishes(
    client, manual_review, run_status
):
    data = manual_review
    async with data.sessions() as session:
        state = await session.get(ProductionState, data.project_id)
        run = await session.get(ProductionRun, state.active_run_id)
        run.status = run_status
        run.progress_metadata = {"scanned_note_match_counts": {
            "N-1": 1, "N-2": 1, "N-3": 1,
        }}
        await session.commit()
    assert (await client.get(f"{data.base}/next")).json()["id"] == str(data.ids[0])
    response = await client.get(f"{data.base}/patient/next")
    assert response.json()["patient_id"] == data.patient_id


async def test_preferred_cursor_overrides_cached_current(manual_review, monkeypatch):
    data = manual_review
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        state = await session.get(ProductionState, data.project_id)

        async def cached_cursor(*args):
            return {"generation": state.generation, "current_id": str(data.ids[0])}

        monkeypatch.setattr(adjudication_service._state_store, "load", cached_cursor)
        cursor = await adjudication_service._sync_cursor(
            session, data.project_id, patient, "reviewer", state.active_run_id,
            state.generation, preferred_id=str(data.ids[1]),
        )
        assert cursor["current_annotation_id"] == str(data.ids[1])


async def test_lock_run_identity_refreshes_cached_state(manual_review):
    data = manual_review
    async with data.sessions() as session:
        cached = await session.get(ProductionState, data.project_id)
        original_generation = cached.generation
        async with data.sessions() as writer:
            await writer.execute(update(ProductionState).where(
                ProductionState.project_id == data.project_id
            ).values(generation=original_generation + 1))
            await writer.commit()
        assert cached.generation == original_generation
        _, generation = await adjudication_service._lock_run_identity(session, data.project_id)
        assert generation == original_generation + 1
        assert cached.generation == generation


async def test_event_action_rolls_back_if_final_results_refresh_fails(
    client, manual_review, monkeypatch
):
    data = manual_review

    async def fail_refresh(session, project_id, patient_id):
        patient = await session.get(Patient, patient_id)
        assert patient.status == PatientStatus.REVIEWED
        assert patient.locked_by is None
        raise RuntimeError("result refresh failed")

    monkeypatch.setattr(adjudication_service, "_refresh_result", fail_refresh)
    with pytest.raises(RuntimeError, match="result refresh failed"):
        await client.post(
            f"{data.base}/{data.ids[0]}/review",
            json={"event_date": "2026-01-10T00:00:00Z", "skip_after_event": True},
        )
    async with data.sessions() as session:
        patient = await session.get(Patient, data.patient_id)
        assert patient.event_date is None
        assert patient.locked_by is None
        assert patient.reviewed_at is None
        rows = [await session.get(Annotation, annotation_id) for annotation_id in data.ids]
        assert all(row.status == "U" and row.review_reason is None for row in rows)
