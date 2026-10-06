"""Tests for the prediction job executor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Import all models so metadata registers all tables
from app.auth.models import User  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.connectors.models import DataSource, Note, Patient, PatientStatus  # noqa: F401
from app.predictors.models import PredictorConfig, PredictorType  # noqa: F401
from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus  # noqa: F401
from app.jobs.models import BackgroundJob, JobStatus, JobType  # noqa: F401
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: F401
from app.evaluation.models import EvaluationSession, SearchMatch, PatientResult  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401
from app.predictors.base import PredictionResult, TokenUsage, PredictorError


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
        text_id="T001", note_date=datetime(2025, 1, 1, tzinfo=UTC), text="note text 1",
    )
    n2 = Note(
        id="note-2", project_id="proj-1", patient_id="pat-2",
        text_id="T002", note_date=datetime(2025, 1, 2, tzinfo=UTC), text="note text 2",
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

    # Existing keyword-matched annotations are the rows scored by the job.
    session.add_all([
        Annotation(
            id="ann-1", project_id="proj-1", patient_id="pat-1", note_id="note-1",
            sentence_id="sent-1", sentence_text=s1.text, matched_tokens="DVT",
            sentence_number=s1.sentence_number, review_status=ReviewStatus.UNREVIEWED,
        ),
        Annotation(
            id="ann-2", project_id="proj-1", patient_id="pat-1", note_id="note-1",
            sentence_id="sent-2", sentence_text=s2.text, matched_tokens="embolus",
            sentence_number=s2.sentence_number, review_status=ReviewStatus.UNREVIEWED,
        ),
        Annotation(
            id="ann-3", project_id="proj-1", patient_id="pat-2", note_id="note-2",
            sentence_id="sent-3", sentence_text=s3.text, matched_tokens="clot",
            sentence_number=s3.sentence_number, review_status=ReviewStatus.UNREVIEWED,
        ),
    ])
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
    """Create a mock predictor that returns a successful PredictionResult."""
    mock_predictor = AsyncMock()
    mock_predictor.predict = AsyncMock(return_value=PredictionResult(
        score=0.15, label=0, model="test-model", reasoning="test reasoning",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    ))
    return mock_predictor


async def test_processes_all_sentences_per_patient(session_factory):
    """Scores 3 existing annotations and completes all-negative LLM patients."""
    async with session_factory() as session:
        await _seed_data(session)

    mock_predictor = _make_mock_predictor()

    with patch("app.jobs.prediction.create_predictor", return_value=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # Verify stats
    assert stats["total_sentences"] == 3
    assert stats["predictions_made"] == 3
    assert stats["annotations_created"] == 3
    assert stats["errors"] == 0
    assert stats["patients_processed"] == 2
    assert stats["total_patients"] == 2
    assert stats["token_usage"]["prompt_tokens"] == 30
    assert stats["token_usage"]["completion_tokens"] == 15
    assert stats["token_usage"]["total_tokens"] == 45

    # Predictions are separate rows; the original annotations remain unreviewed.
    async with session_factory() as session:
        result = await session.execute(select(AnnotationPrediction))
        predictions = result.scalars().all()
        assert len(predictions) == 3
        assert all(prediction.predicted_label == 0 for prediction in predictions)

        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert len(annotations) == 3
        assert all(annotation.review_status == ReviewStatus.UNREVIEWED for annotation in annotations)
        assert all(annotation.predicted_score is None for annotation in annotations)

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
    """Pre-sets is_cancelled=True on job. Verifies only first patient processed
    (2 of 3 sentences) and job status is CANCELLED."""
    async with session_factory() as session:
        await _seed_data(session, is_cancelled=True)

    mock_predictor = _make_mock_predictor()

    with patch("app.jobs.prediction.create_predictor", return_value=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # Cancellation is checked before each patient, so no patients should be processed
    # because is_cancelled=True from the start
    assert stats["patients_processed"] == 0
    assert stats["annotations_created"] == 0

    # Verify job status
    async with session_factory() as session:
        result = await session.execute(select(AnnotationPrediction))
        assert result.scalars().all() == []
        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert len(annotations) == 3
        assert all(annotation.review_status == ReviewStatus.UNREVIEWED for annotation in annotations)
        job = await session.get(BackgroundJob, "job-1")
        assert job.status == JobStatus.CANCELLED
        assert job.completed_at is not None


async def test_handles_prediction_errors_gracefully(session_factory):
    """One prediction throws PredictorError. Verifies job still completes,
    successful verdicts persist, the failed verdict is absent, and errors are counted."""
    async with session_factory() as session:
        await _seed_data(session)

    mock_predictor = _make_mock_predictor()
    call_count = 0

    async def _predict_with_error(text: str) -> PredictionResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise PredictorError("Model unavailable")
        return PredictionResult(
            score=0.1, label=0, model="test-model", reasoning="ok",
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    mock_predictor.predict = _predict_with_error

    with patch("app.jobs.prediction.create_predictor", return_value=mock_predictor):
        from app.jobs.prediction import execute_prediction_job
        stats = await execute_prediction_job("proj-1", "job-1", session_factory)

    # All 3 existing annotations were considered, but 1 prediction failed.
    assert stats["total_sentences"] == 3
    assert stats["predictions_made"] == 2
    assert stats["annotations_created"] == 3
    assert stats["errors"] == 1

    # Successful predictions persist separately; the failed annotation has no row.
    async with session_factory() as session:
        result = await session.execute(
            select(AnnotationPrediction).order_by(AnnotationPrediction.annotation_id)
        )
        predictions = result.scalars().all()
        assert len(predictions) == 2
        assert {prediction.annotation_id for prediction in predictions} == {"ann-1", "ann-3"}

        result = await session.execute(select(Annotation))
        annotations = result.scalars().all()
        assert len(annotations) == 3
        assert all(annotation.review_status == ReviewStatus.UNREVIEWED for annotation in annotations)

        # Patient 1 has an unscored annotation, so not all keyword matches are negative.
        patient_1 = await session.get(Patient, "pat-1")
        patient_2 = await session.get(Patient, "pat-2")
        assert patient_1.status == PatientStatus.NEW
        assert patient_1.review_source is None
        assert patient_2.status == PatientStatus.REVIEWED
        assert patient_2.review_source == "llm"

        # Job should be COMPLETED despite errors
        job = await session.get(BackgroundJob, "job-1")
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100
