"""Tests for pipeline data models."""
import pytest

from tests.conftest import seed_project_and_user


async def _get_session(app):
    from app.common.database import get_session
    gen = app.dependency_overrides[get_session]()
    session = await gen.__anext__()
    yield session
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass


class TestEventConfigModel:
    async def test_create_event_config(self, app):
        from app.pipeline.models import EventConfig
        await seed_project_and_user(app)
        async for session in _get_session(app):
            config = EventConfig(
                project_id="proj-1",
                name="Myocardial Infarction",
                description="Confirmed MI event",
                include_criteria="Troponin elevation, ECG changes",
                exclude_criteria="Rule-out, family history only",
                search_patterns={
                    "keywords": ["troponin", "MI"],
                    "regex_patterns": [r"troponin.*elevated"],
                    "exclusion_patterns": ["rule.?out"],
                },
                llm_provider="ollama",
                llm_model="llama3",
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            assert config.id is not None
            assert config.is_committed is False
            assert config.confidence_threshold is None


class TestPipelineRunModel:
    async def test_create_pipeline_run(self, app):
        from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus
        await seed_project_and_user(app)
        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="sample", status=PipelineRunStatus.QUEUED,
                config_snapshot={"name": "MI"}, sample_size=50,
                total_patients=50, created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            assert run.id is not None
            assert run.is_cancelled is False
            assert run.snapshot_version == 1

    async def test_pipeline_run_snapshot_version(self, app):
        from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus
        await seed_project_and_user(app)
        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="full", status=PipelineRunStatus.QUEUED,
                config_snapshot={}, total_patients=100,
                created_by="user-1", snapshot_version=2,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            assert run.snapshot_version == 2


class TestPatientTaskModel:
    async def test_create_patient_task(self, app):
        from app.pipeline.models import (
            EventConfig,
            PatientTask,
            PatientTaskStatus,
            PipelineRun,
            PipelineRunStatus,
        )
        await seed_project_and_user(app)
        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="full", status=PipelineRunStatus.QUEUED,
                config_snapshot={}, total_patients=1, created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            task = PatientTask(
                pipeline_run_id=run.id, patient_id="patient-1",
                status=PatientTaskStatus.QUEUED,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            assert task.id is not None
            assert task.notes_matched == 0
            assert task.finding_label is None

    async def test_valid_state_transitions(self, app):
        """PatientTask should allow valid state transitions."""
        from app.pipeline.models import (
            EventConfig,
            PatientTask,
            PatientTaskStatus,
            PipelineRun,
            PipelineRunStatus,
        )
        await seed_project_and_user(app)
        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="full", status=PipelineRunStatus.QUEUED,
                config_snapshot={}, total_patients=1, created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            task = PatientTask(
                pipeline_run_id=run.id, patient_id="patient-1",
                status=PatientTaskStatus.QUEUED,
            )
            # queued -> processing
            task.transition_status(PatientTaskStatus.PROCESSING)
            assert task.status == PatientTaskStatus.PROCESSING

            # processing -> completed
            task.transition_status(PatientTaskStatus.COMPLETED)
            assert task.status == PatientTaskStatus.COMPLETED

    async def test_invalid_state_transition_raises(self, app):
        """PatientTask should reject invalid transitions."""
        from app.pipeline.models import PatientTask, PatientTaskStatus

        task = PatientTask(
            pipeline_run_id=1, patient_id="patient-1",
            status=PatientTaskStatus.COMPLETED,
        )
        with pytest.raises(ValueError, match="Invalid transition"):
            task.transition_status(PatientTaskStatus.QUEUED)

    async def test_retry_transition(self, app):
        """Failed tasks can be retried (failed -> queued)."""
        from app.pipeline.models import PatientTask, PatientTaskStatus

        task = PatientTask(
            pipeline_run_id=1, patient_id="patient-1",
            status=PatientTaskStatus.FAILED,
        )
        task.transition_status(PatientTaskStatus.QUEUED)
        assert task.status == PatientTaskStatus.QUEUED


class TestAnnotationPipelineLinkage:
    async def test_annotation_with_pipeline_fields(self, app):
        """Annotation can link to pipeline run and patient task."""
        from app.annotations.models import Annotation, ReviewStatus

        ann = Annotation(
            project_id="proj-1",
            patient_id="patient-1",
            note_id="note-1",
            sentence_id="sent-1",
            sentence_text="Troponin elevated",
            pipeline_run_id="run-1",
            patient_task_id=1,
            predicted_reasoning="Troponin level elevated at 2.4",
            reviewer_label="positive",
            reviewer_notes="Confirmed by Dr. Smith",
            review_status=ReviewStatus.PENDING,
        )
        assert ann.pipeline_run_id == "run-1"
        assert ann.patient_task_id == 1
        assert ann.predicted_reasoning == "Troponin level elevated at 2.4"
        assert ann.reviewer_label == "positive"
        assert ann.review_status == ReviewStatus.PENDING

    async def test_annotation_without_pipeline_fields(self, app):
        """Existing annotations work without pipeline fields."""
        from app.annotations.models import Annotation, ReviewStatus

        ann = Annotation(
            project_id="proj-1",
            patient_id="patient-1",
            note_id="note-1",
            sentence_id="sent-1",
            sentence_text="Some text",
            review_status=ReviewStatus.UNREVIEWED,
        )
        assert ann.pipeline_run_id is None
        assert ann.patient_task_id is None
        assert ann.predicted_reasoning is None

    async def test_review_status_has_pipeline_values(self, app):
        from app.annotations.models import ReviewStatus
        assert ReviewStatus.PENDING == "pending"
        assert ReviewStatus.CONFIRMED == "confirmed"
        assert ReviewStatus.REJECTED == "rejected"


class TestEvidenceModel:
    async def test_create_evidence(self, app):
        from app.pipeline.models import Evidence
        ev = Evidence(
            patient_task_id=1, note_id="note-1",
            text="troponin elevated at 2.4 ng/mL",
            start_pos=120, end_pos=155,
            match_source="keyword", match_pattern="troponin",
        )
        assert ev.match_source == "keyword"
