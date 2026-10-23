"""Tests for the prediction job executor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401

# Import all models so metadata registers all tables
from app.auth.models import User  # noqa: F401
from app.connectors.models import DataSource, Note, Patient, PatientStatus  # noqa: F401
from app.evaluation.models import EvaluationSession, PatientResult, SearchMatch  # noqa: F401
from app.jobs.models import BackgroundJob, JobStatus, JobType  # noqa: F401
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: F401
from app.predictors.base import PredictorError
from app.predictors.models import PredictorConfig, PredictorType  # noqa: F401
from app.production.classifier import NoteClassification
from app.production.models import NotePrediction
from app.projects.models import Project, ProjectMember  # noqa: F401


def _assert_all_unreviewed(annotations: list[Annotation]) -> None:
    assert all(a.review_status == ReviewStatus.UNREVIEWED for a in annotations)


async def _seed_data(session: AsyncSession, is_cancelled: bool = False):
    """Seed 2 patients with 3 total target sentences and an active predictor."""
    # User
    user = User(id="user-1", email="test@test.com", name="Test", password_hash="x")
    session.add(user)
    await session.flush()

    # Project
    project = Project(id="proj-1", name="Test Project", owner_id="user-1")
    session.add(project)
    await session.flush()

    # Patients
    p1 = Patient(id="pat-1", project_id="proj-1", patient_id_ext="EXT-001")
    p2 = Patient(id="pat-2", project_id="proj-1", patient_id_ext="EXT-002")
    session.add_all([p1, p2])
    await session.flush()

    # Notes
    n1 = Note(
        id="note-1", project_id="proj-1", patient_id="pat-1",
        patient_id_ext="EXT-001", text_id="T001",
        note_date=datetime(2025, 1, 1, tzinfo=UTC),
        text="Patient has DVT. Confirmed embolus.",
    )
    n2 = Note(
        id="note-2", project_id="proj-1", patient_id="pat-2",
        patient_id_ext="EXT-002", text_id="T002",
        note_date=datetime(2025, 1, 2, tzinfo=UTC), text="No evidence of clot.",
    )
    session.add_all([n1, n2])
    await session.flush()

    # Sentences: 2 target for patient 1, 1 target for patient 2
    s1 = Sentence(
        id="sent-1", note_id="note-1", project_id="proj-1",
        sentence_number=0, text="Patient has DVT.", start_pos=0, end_pos=16,
        is_target=True, matched_tokens=["DVT"],
    )
    s2 = Sentence(
        id="sent-2", note_id="note-1", project_id="proj-1",
        sentence_number=1, text="Confirmed embolus.", start_pos=17, end_pos=35,
        is_target=True, matched_tokens=["embolus"],
    )
    s3 = Sentence(
        id="sent-3", note_id="note-2", project_id="proj-1",
        sentence_number=0, text="No evidence of clot.", start_pos=0, end_pos=20,
        is_target=True, matched_tokens=["clot"],
    )
    session.add_all([s1, s2, s3])
    await session.flush()

    session.add(SearchQuery(
        project_id="proj-1", query="DVT OR embolus OR clot", exclude_negated=False,
        created_by="user-1",
    ))
    await session.flush()

    # Predictor config (active)
    pc = PredictorConfig(
        id="pred-1", project_id="proj-1", predictor_type=PredictorType.LLM,
        name="test-llm", config={"provider": "ollama", "model": "llama3"},
        is_active=True, created_by="user-1",
    )
    session.add(pc)
    await session.flush()

    # Background job
    job = BackgroundJob(
        id="job-1", project_id="proj-1", job_type=JobType.PREDICTION,
        is_cancelled=is_cancelled,
    )
    session.add(job)
    await session.flush()

    await session.commit()


def _make_mock_predictor():
    """Create a full-note classifier returning an explicit negative verdict."""
    return AsyncMock(return_value=NoteClassification(
        score=0.95, label=0, reasoning="test reasoning", evidence_spans=[],
        token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    ))


async def test_processes_all_sentences_per_patient(session_factory):
    """Classify two complete notes for three matches and complete negative patients."""
    async with session_factory() as session:
        await _seed_data(session)

    mock_predictor = _make_mock_predictor()

    with patch("app.production.service.classify_note", new=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # Verify stats
    assert stats["total_sentences"] == 3
    assert stats["predictions_made"] == 2
    assert stats["annotations_created"] == 3
    assert stats["errors"] == 0
    assert stats["patients_processed"] == 2
    assert stats["total_patients"] == 2
    assert stats["token_usage"]["prompt_tokens"] == 20
    assert stats["token_usage"]["completion_tokens"] == 10
    assert stats["token_usage"]["total_tokens"] == 30
    assert {call.args[0] for call in mock_predictor.await_args_list} == {
        "Patient has DVT. Confirmed embolus.", "No evidence of clot.",
    }

    # Predictions are separate rows; the original annotations remain unreviewed.
    async with session_factory() as session:
        result = await session.execute(select(NotePrediction))
        predictions = result.scalars().all()
        assert len(predictions) == 2
        assert all(prediction.label == 0 for prediction in predictions)
        assert all(prediction.status == "succeeded" for prediction in predictions)

        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert len(annotations) == 3
        assert all(annotation.status == "R" for annotation in annotations)
        assert all(annotation.review_reason == "llm_negative" for annotation in annotations)
        assert all(annotation.prediction_id in {item.id for item in predictions}
               for annotation in annotations)
        assert list(await session.scalars(select(AnnotationPrediction))) == []

        # The helper completes a patient only when every annotation is negative.
        patient_1 = await session.get(Patient, "pat-1")
        patient_2 = await session.get(Patient, "pat-2")
        assert patient_1.status == PatientStatus.REVIEWED
        assert patient_1.review_source == "llm"
        assert patient_2.status == PatientStatus.REVIEWED
        assert patient_2.review_source == "llm"

        # Verify job status
        job = await session.get(BackgroundJob, "job-1")
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100
        assert job.completed_at is not None


async def test_cancellation_stops_after_current_patient(session_factory):
    """A pre-cancelled job must not classify notes or create production matches."""
    async with session_factory() as session:
        await _seed_data(session, is_cancelled=True)

    mock_predictor = _make_mock_predictor()

    with patch("app.production.service.classify_note", new=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # Cancellation is checked before each patient, so no patients should be processed
    # because is_cancelled=True from the start
    assert stats["patients_processed"] == 0
    assert stats["annotations_created"] == 0
    mock_predictor.assert_not_awaited()

    # Verify job status
    async with session_factory() as session:
        result = await session.execute(select(AnnotationPrediction))
        assert result.scalars().all() == []
        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert annotations == []
        assert list(await session.scalars(select(NotePrediction))) == []
        job = await session.get(BackgroundJob, "job-1")
        assert job.status == JobStatus.CANCELLED
        assert job.completed_at is not None


async def test_handles_prediction_errors_gracefully(session_factory):
    """A failed note blocks its patient without discarding another patient's verdict."""
    async with session_factory() as session:
        await _seed_data(session)

    mock_predictor = _make_mock_predictor()
    call_count = 0

    async def _predict_with_error(text: str, config, **kwargs) -> NoteClassification:
        nonlocal call_count
        call_count += 1
        if "DVT" in text:
            raise PredictorError("Model unavailable")
        return NoteClassification(
            score=0.95, label=0, reasoning="ok", evidence_spans=[],
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    mock_predictor.side_effect = _predict_with_error

    with patch("app.production.service.classify_note", new=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # All 3 existing annotations were considered, but 1 prediction failed.
    assert stats["total_sentences"] == 3
    assert stats["predictions_made"] == 1
    assert stats["annotations_created"] == 3
    assert stats["errors"] == 1
    assert call_count == 2

    # Successful predictions persist separately; the failed annotation has no row.
    async with session_factory() as session:
        result = await session.execute(
            select(NotePrediction).order_by(NotePrediction.text_id)
        )
        predictions = result.scalars().all()
        assert len(predictions) == 2
        assert predictions[0].status == "failed"
        assert predictions[0].label is None
        assert "Model unavailable" in predictions[0].error
        assert predictions[1].status == "succeeded"
        assert predictions[1].label == 0

        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert len(annotations) == 3
        _assert_all_unreviewed([item for item in annotations if item.patient_id == "EXT-001"])
        assert all(item.review_reason == "llm_negative" for item in annotations
               if item.patient_id == "EXT-002")

        # Patient 1 has an unscored annotation, so not all keyword matches are negative.
        patient_1 = await session.get(Patient, "pat-1")
        patient_2 = await session.get(Patient, "pat-2")
        assert patient_1.status == PatientStatus.NLP_PROCESSING
        assert patient_1.review_source is None
        assert patient_2.status == PatientStatus.REVIEWED
        assert patient_2.review_source == "llm"

        job = await session.get(BackgroundJob, "job-1")
        assert job.status == JobStatus.FAILED
        assert job.progress == 100
