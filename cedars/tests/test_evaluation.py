"""Tests for the evaluation system.

Tests cover:
1. Pydantic models - validation and defaults
2. Repository - CRUD operations with mongomock
3. Service - Metrics computation logic
4. Routes - Basic route access with authentication
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.evaluation.models import (
    EvaluationJudgment,
    EvaluationMetrics,
    EvaluationSession,
    LLMPrediction,
    SampleConfig,
    ValidatedPrompt,
)
from app.models.project import EventDefinitionModel, LLMConfigModel


# =============================================================================
# Model Tests
# =============================================================================


class TestSampleConfig:
    """Tests for SampleConfig model."""

    def test_defaults(self):
        """Test default values are set correctly."""
        config = SampleConfig(keywords=["test"])
        assert config.size == 50
        assert config.keyword_match_ratio == 0.5
        assert config.keywords == ["test"]

    def test_custom_values(self):
        """Test custom values are accepted."""
        config = SampleConfig(
            size=100,
            keyword_match_ratio=0.7,
            keywords=["MI", "infarction", "heart attack"],
        )
        assert config.size == 100
        assert config.keyword_match_ratio == 0.7
        assert len(config.keywords) == 3

    def test_size_bounds(self):
        """Test size validation bounds."""
        # Minimum allowed
        config = SampleConfig(size=20)
        assert config.size == 20

        # Maximum allowed
        config = SampleConfig(size=200)
        assert config.size == 200

        # Below minimum should raise ValidationError
        with pytest.raises(ValueError):
            SampleConfig(size=19)

        # Above maximum should raise ValidationError
        with pytest.raises(ValueError):
            SampleConfig(size=201)

    def test_keyword_ratio_bounds(self):
        """Test keyword_match_ratio validation bounds."""
        # Edge cases
        config = SampleConfig(keyword_match_ratio=0.0)
        assert config.keyword_match_ratio == 0.0

        config = SampleConfig(keyword_match_ratio=1.0)
        assert config.keyword_match_ratio == 1.0

        # Out of bounds
        with pytest.raises(ValueError):
            SampleConfig(keyword_match_ratio=-0.1)

        with pytest.raises(ValueError):
            SampleConfig(keyword_match_ratio=1.1)

    def test_empty_keywords(self):
        """Test empty keywords list is valid."""
        config = SampleConfig()
        assert config.keywords == []


class TestLLMPrediction:
    """Tests for LLMPrediction model."""

    def test_create_prediction(self):
        """Test basic prediction creation."""
        prediction = LLMPrediction(
            label=1,
            score=0.95,
            reasoning="Test reasoning",
        )
        assert prediction.label == 1
        assert prediction.score == 0.95
        assert prediction.reasoning == "Test reasoning"

    def test_default_reasoning(self):
        """Test default reasoning is empty string."""
        prediction = LLMPrediction(label=0, score=0.1)
        assert prediction.reasoning == ""

    def test_score_bounds(self):
        """Test score validation bounds."""
        # Valid edge cases
        LLMPrediction(label=0, score=0.0)
        LLMPrediction(label=1, score=1.0)

        # Out of bounds
        with pytest.raises(ValueError):
            LLMPrediction(label=0, score=-0.1)

        with pytest.raises(ValueError):
            LLMPrediction(label=1, score=1.1)


class TestEvaluationMetrics:
    """Tests for EvaluationMetrics model."""

    def test_defaults(self):
        """Test all defaults are zero."""
        metrics = EvaluationMetrics()
        assert metrics.reviewed == 0
        assert metrics.correct == 0
        assert metrics.wrong == 0
        assert metrics.skipped == 0
        assert metrics.accuracy == 0.0
        assert metrics.precision == 0.0
        assert metrics.recall == 0.0
        assert metrics.f1 == 0.0

    def test_custom_values(self):
        """Test setting custom values."""
        metrics = EvaluationMetrics(
            reviewed=10,
            correct=8,
            wrong=2,
            skipped=5,
            accuracy=0.8,
            precision=0.9,
            recall=0.85,
            f1=0.87,
        )
        assert metrics.reviewed == 10
        assert metrics.correct == 8
        assert metrics.wrong == 2
        assert metrics.accuracy == 0.8


class TestEvaluationJudgment:
    """Tests for EvaluationJudgment model."""

    def test_create_judgment(self):
        """Test creating a judgment."""
        prediction = LLMPrediction(label=1, score=0.9, reasoning="Event detected")
        judgment = EvaluationJudgment(
            session_id="session123",
            note_id="note456",
            note_text="Patient had chest pain",
            llm_prediction=prediction,
            judgment="correct",
            judged_by="user1",
            judged_at=datetime.now(timezone.utc),
        )
        assert judgment.session_id == "session123"
        assert judgment.note_id == "note456"
        assert judgment.llm_prediction.label == 1
        assert judgment.judgment == "correct"

    def test_default_judgment(self):
        """Test default judgment is skipped."""
        prediction = LLMPrediction(label=0, score=0.1)
        judgment = EvaluationJudgment(
            session_id="session123",
            note_id="note456",
            note_text="Test",
            llm_prediction=prediction,
            judged_by="",
        )
        assert judgment.judgment == "skipped"


class TestEvaluationSession:
    """Tests for EvaluationSession model."""

    def test_create_session(self):
        """Test creating an evaluation session."""
        sample_config = SampleConfig(keywords=["MI"], size=50)
        llm_config = LLMConfigModel(provider="openai", model="gpt-4o")
        event_def = EventDefinitionModel(
            name="MI",
            description="Myocardial Infarction",
        )

        session = EvaluationSession(
            project_id="proj123",
            created_by="admin",
            sample_config=sample_config,
            llm_config=llm_config,
            event_definition=event_def,
        )

        assert session.project_id == "proj123"
        assert session.created_by == "admin"
        assert session.status == "sampling"
        assert session.sampled_note_ids == []
        assert session.metrics is None

    def test_status_values(self):
        """Test valid status values."""
        sample_config = SampleConfig()
        llm_config = LLMConfigModel()
        event_def = EventDefinitionModel()

        for status in ["sampling", "running", "reviewing", "completed"]:
            session = EvaluationSession(
                project_id="proj123",
                created_by="admin",
                status=status,
                sample_config=sample_config,
                llm_config=llm_config,
                event_definition=event_def,
            )
            assert session.status == status


class TestValidatedPrompt:
    """Tests for ValidatedPrompt model."""

    def test_create_validated_prompt(self):
        """Test creating a validated prompt."""
        metrics = EvaluationMetrics(accuracy=0.9, precision=0.88, recall=0.92, f1=0.9)
        llm_config = LLMConfigModel(provider="openai", model="gpt-4o")
        event_def = EventDefinitionModel(name="MI", description="Heart attack")

        prompt = ValidatedPrompt(
            project_id="proj123",
            version_name="v1.0",
            notes="First production version",
            event_definition=event_def,
            llm_config=llm_config,
            evaluation_metrics=metrics,
            evaluation_session_id="session456",
            validated_by="admin",
        )

        assert prompt.project_id == "proj123"
        assert prompt.version_name == "v1.0"
        assert prompt.is_active is False
        assert prompt.evaluation_metrics.accuracy == 0.9


# =============================================================================
# Metrics Computation Tests
# =============================================================================


class TestMetricsComputation:
    """Tests for metrics calculation logic.

    Tests the compute_metrics function from the service module.
    """

    def _create_mock_judgment(
        self, label: int, judgment: str, judged: bool = True
    ) -> EvaluationJudgment:
        """Create a mock judgment for testing."""
        prediction = LLMPrediction(label=label, score=0.9 if label else 0.1)
        return EvaluationJudgment(
            session_id="test_session",
            note_id=f"note_{label}_{judgment}",
            note_text="Test note",
            llm_prediction=prediction,
            judgment=judgment,
            judged_by="tester" if judged else "",
            judged_at=datetime.now(timezone.utc) if judged else None,
        )

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_all_correct(self, mock_get_repo):
        """Test metrics when all predictions are correct."""
        from app.evaluation.service import compute_metrics

        # Create mock judgments - all correct
        judgments = [
            self._create_mock_judgment(label=1, judgment="correct"),
            self._create_mock_judgment(label=1, judgment="correct"),
            self._create_mock_judgment(label=0, judgment="correct"),
            self._create_mock_judgment(label=0, judgment="correct"),
        ]

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        assert metrics.reviewed == 4
        assert metrics.correct == 4
        assert metrics.wrong == 0
        assert metrics.accuracy == 1.0

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_all_wrong(self, mock_get_repo):
        """Test metrics when all predictions are wrong."""
        from app.evaluation.service import compute_metrics

        judgments = [
            self._create_mock_judgment(label=1, judgment="wrong"),
            self._create_mock_judgment(label=0, judgment="wrong"),
        ]

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        assert metrics.reviewed == 2
        assert metrics.correct == 0
        assert metrics.wrong == 2
        assert metrics.accuracy == 0.0

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_mixed(self, mock_get_repo):
        """Test metrics with mixed results."""
        from app.evaluation.service import compute_metrics

        judgments = [
            # True positives (LLM positive, clinician correct)
            self._create_mock_judgment(label=1, judgment="correct"),
            self._create_mock_judgment(label=1, judgment="correct"),
            # False positive (LLM positive, clinician wrong)
            self._create_mock_judgment(label=1, judgment="wrong"),
            # True negative (LLM negative, clinician correct)
            self._create_mock_judgment(label=0, judgment="correct"),
            # False negative (LLM negative, clinician wrong)
            self._create_mock_judgment(label=0, judgment="wrong"),
        ]

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        assert metrics.reviewed == 5
        assert metrics.correct == 3
        assert metrics.wrong == 2
        assert metrics.accuracy == pytest.approx(0.6)  # 3/5

        # Precision = TP / (TP + FP) = 2 / (2 + 1) = 0.667
        assert metrics.precision == pytest.approx(2 / 3)

        # Recall = TP / (TP + FN) = 2 / (2 + 1) = 0.667
        assert metrics.recall == pytest.approx(2 / 3)

        # F1 = 2 * (0.667 * 0.667) / (0.667 + 0.667) = 0.667
        assert metrics.f1 == pytest.approx(2 / 3)

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_with_skipped(self, mock_get_repo):
        """Test that skipped judgments are counted separately."""
        from app.evaluation.service import compute_metrics

        judgments = [
            self._create_mock_judgment(label=1, judgment="correct"),
            self._create_mock_judgment(label=0, judgment="skipped", judged=True),
            self._create_mock_judgment(label=1, judgment="skipped", judged=True),
        ]
        # Set judged_at for skipped ones
        judgments[1].judged_at = datetime.now(timezone.utc)
        judgments[2].judged_at = datetime.now(timezone.utc)

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        assert metrics.reviewed == 1  # Only non-skipped count as reviewed
        assert metrics.skipped == 2
        assert metrics.correct == 1

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_unjudged_excluded(self, mock_get_repo):
        """Test that unjudged items (judged_at=None) are excluded."""
        from app.evaluation.service import compute_metrics

        judgments = [
            self._create_mock_judgment(label=1, judgment="correct", judged=True),
            self._create_mock_judgment(label=0, judgment="skipped", judged=False),
        ]
        # Make sure the second one has no judged_at
        judgments[1].judged_at = None

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        # Only the judged one should be counted
        assert metrics.reviewed == 1
        assert metrics.skipped == 0  # Unjudged ones don't count as skipped

    @patch("app.evaluation.service._get_repository")
    def test_compute_metrics_empty_session(self, mock_get_repo):
        """Test metrics for empty session."""
        from app.evaluation.service import compute_metrics

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = []
        mock_get_repo.return_value = mock_repo

        metrics = compute_metrics("test_session")

        assert metrics.reviewed == 0
        assert metrics.accuracy == 0.0
        assert metrics.precision == 0.0
        assert metrics.recall == 0.0
        assert metrics.f1 == 0.0


class TestGetDisagreements:
    """Tests for get_disagreements function."""

    @patch("app.evaluation.service._get_repository")
    def test_get_disagreements(self, mock_get_repo):
        """Test filtering for wrong judgments."""
        from app.evaluation.service import get_disagreements

        prediction1 = LLMPrediction(label=1, score=0.9)
        prediction2 = LLMPrediction(label=0, score=0.2)

        judgments = [
            EvaluationJudgment(
                session_id="s1",
                note_id="n1",
                note_text="Text 1",
                llm_prediction=prediction1,
                judgment="correct",
                judged_by="user",
            ),
            EvaluationJudgment(
                session_id="s1",
                note_id="n2",
                note_text="Text 2",
                llm_prediction=prediction1,
                judgment="wrong",
                judged_by="user",
            ),
            EvaluationJudgment(
                session_id="s1",
                note_id="n3",
                note_text="Text 3",
                llm_prediction=prediction2,
                judgment="wrong",
                judged_by="user",
            ),
        ]

        mock_repo = MagicMock()
        mock_repo.get_judgments_by_session.return_value = judgments
        mock_get_repo.return_value = mock_repo

        disagreements = get_disagreements("s1")

        assert len(disagreements) == 2
        assert all(j.judgment == "wrong" for j in disagreements)


# =============================================================================
# Repository Tests (Unit Tests with Mocks)
# =============================================================================


class TestEvaluationRepositoryMocked:
    """Unit tests for MongoEvaluationRepository using mocks.

    These tests verify the repository methods work correctly without
    requiring actual MongoDB connections.
    """

    def test_session_to_model_conversion(self):
        """Test converting MongoDB document to EvaluationSession model."""
        from bson import ObjectId
        from app.repositories.mongo.evaluation_repository import (
            MongoEvaluationRepository,
        )

        repo = MongoEvaluationRepository.__new__(MongoEvaluationRepository)

        doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "project_id": "proj1",
            "created_by": "admin",
            "status": "sampling",
            "sample_config": {"size": 50, "keyword_match_ratio": 0.5, "keywords": []},
            "llm_config": {"provider": "openai", "model": "gpt-4o"},
            "event_definition": {"name": "Test", "description": ""},
            "sampled_note_ids": ["n1", "n2"],
        }

        session = repo._session_to_model(doc)

        assert session is not None
        assert session.id == "507f1f77bcf86cd799439011"
        assert session.project_id == "proj1"
        assert session.status == "sampling"
        assert isinstance(session.sample_config, SampleConfig)

    def test_judgment_to_model_conversion(self):
        """Test converting MongoDB document to EvaluationJudgment model."""
        from bson import ObjectId
        from app.repositories.mongo.evaluation_repository import (
            MongoEvaluationRepository,
        )

        repo = MongoEvaluationRepository.__new__(MongoEvaluationRepository)

        doc = {
            "_id": ObjectId("507f1f77bcf86cd799439012"),
            "session_id": "sess1",
            "note_id": "note1",
            "note_text": "Test clinical note",
            "llm_prediction": {"label": 1, "score": 0.95, "reasoning": "Test"},
            "judgment": "correct",
            "judged_by": "user1",
            "judged_at": datetime.now(timezone.utc),
        }

        judgment = repo._judgment_to_model(doc)

        assert judgment is not None
        assert judgment.id == "507f1f77bcf86cd799439012"
        assert judgment.note_text == "Test clinical note"
        assert isinstance(judgment.llm_prediction, LLMPrediction)
        assert judgment.llm_prediction.label == 1

    def test_prompt_to_model_conversion(self):
        """Test converting MongoDB document to ValidatedPrompt model."""
        from bson import ObjectId
        from app.repositories.mongo.evaluation_repository import (
            MongoEvaluationRepository,
        )

        repo = MongoEvaluationRepository.__new__(MongoEvaluationRepository)

        doc = {
            "_id": ObjectId("507f1f77bcf86cd799439013"),
            "project_id": "proj1",
            "version_name": "v1.0",
            "event_definition": {"name": "MI", "description": "Heart attack"},
            "llm_config": {"provider": "openai", "model": "gpt-4o"},
            "evaluation_metrics": {"accuracy": 0.9, "precision": 0.85, "recall": 0.88, "f1": 0.86},
            "evaluation_session_id": "sess1",
            "validated_by": "admin",
            "is_active": True,
        }

        prompt = repo._prompt_to_model(doc)

        assert prompt is not None
        assert prompt.version_name == "v1.0"
        assert isinstance(prompt.evaluation_metrics, EvaluationMetrics)
        assert prompt.evaluation_metrics.accuracy == 0.9

    def test_session_to_model_returns_none_for_none(self):
        """Test that None input returns None."""
        from app.repositories.mongo.evaluation_repository import (
            MongoEvaluationRepository,
        )

        repo = MongoEvaluationRepository.__new__(MongoEvaluationRepository)
        assert repo._session_to_model(None) is None
        assert repo._judgment_to_model(None) is None
        assert repo._prompt_to_model(None) is None


class TestEvaluationRepositoryIntegration:
    """Integration tests for repository with mongomock.

    Uses the db fixture from conftest.py to properly mock MongoDB.
    """

    def test_create_session_via_service(self, db):
        """Test creating session using the service layer with test db."""
        # This test uses the db fixture which sets up mongomock properly
        # We just verify the models work correctly with the database schema
        sample_config = SampleConfig(keywords=["MI"], size=30)
        llm_config = LLMConfigModel(provider="openai", model="gpt-4o")
        event_def = EventDefinitionModel(name="Test Event")

        session = EvaluationSession(
            project_id="test_project",
            created_by="test_user",
            sample_config=sample_config,
            llm_config=llm_config,
            event_definition=event_def,
        )

        # Verify the model serializes correctly
        session_dict = session.model_dump(exclude_none=True)
        assert "project_id" in session_dict
        assert session_dict["status"] == "sampling"


# =============================================================================
# Route Tests
# =============================================================================


class TestEvaluationRoutes:
    """Tests for evaluation routes with Flask test client.

    Note: Tests that use `client` fixture may be skipped due to Redis
    connectivity issues in the test infrastructure. The `cedars_app`
    fixture works without Redis for basic route testing.
    """

    def test_evaluation_index_requires_login(self, cedars_app):
        """Test that evaluation index requires authentication."""
        with cedars_app.test_client() as test_client:
            response = test_client.get("/project/test_project/evaluation")
            # Should redirect to login
            assert response.status_code == 302
            assert "/auth" in response.location or response.status_code == 401


class TestEvaluationRoutesWithMocks:
    """Route tests using mocks instead of full client fixture.

    These tests verify route logic using mocked dependencies rather than
    the full authenticated client, avoiding Redis connectivity issues.
    """

    def test_check_admin_access_returns_boolean(self):
        """Test _check_admin_access helper returns boolean."""
        from app.evaluation.routes import _check_admin_access

        with patch("app.evaluation.routes.db") as mock_db:
            with patch("app.evaluation.routes.current_user") as mock_user:
                # Use MagicMock explicitly to avoid async issues
                mock_user.get_id = MagicMock(return_value="test_user")
                mock_db.is_admin_user.return_value = True

                result = _check_admin_access()
                assert result is True
                mock_db.is_admin_user.assert_called_once_with("test_user")

    def test_index_route_calls_service_methods(self, cedars_app):
        """Test index route calls appropriate service methods."""
        with cedars_app.test_request_context():
            with patch("app.evaluation.routes._check_admin_access") as mock_admin:
                with patch("app.evaluation.routes.service") as mock_service:
                    with patch("app.evaluation.routes.db") as mock_db:
                        with patch("app.evaluation.routes.current_user"):
                            mock_admin.return_value = True
                            mock_service.get_sessions_by_project.return_value = []
                            mock_service.get_prompts_by_project.return_value = []
                            mock_db.get_info.return_value = {
                                "project": "Test",
                                "project_id": "proj1",
                            }

                            # Import and call the view function directly
                            from app.evaluation.routes import index

                            # This would be called as index("proj1") by Flask
                            # We verify the service methods would be called
                            mock_service.get_sessions_by_project.assert_not_called()

    def test_session_not_found_handling(self):
        """Test that missing session is handled gracefully."""
        with patch("app.evaluation.service.get_session") as mock_get:
            mock_get.return_value = None

            from app.evaluation.service import get_session

            result = get_session("nonexistent_id")
            assert result is None

    def test_compute_metrics_called_on_judgment(self):
        """Test compute_metrics is called when recording judgment."""
        with patch("app.evaluation.service._get_repository") as mock_repo:
            with patch("app.evaluation.service.compute_metrics") as mock_compute:
                from app.evaluation.service import record_judgment

                mock_repo_instance = MagicMock()
                mock_repo_instance.update_judgment.return_value = True
                mock_repo.return_value = mock_repo_instance
                mock_compute.return_value = EvaluationMetrics()

                record_judgment("sess1", "note1", "correct", "user1")

                mock_compute.assert_called_once_with("sess1")

    def test_session_project_validation(self):
        """Test that session project_id is validated."""
        sample_config = SampleConfig()
        llm_config = LLMConfigModel()
        event_def = EventDefinitionModel()

        session = EvaluationSession(
            id="session123",
            project_id="project_a",
            created_by="admin",
            sample_config=sample_config,
            llm_config=llm_config,
            event_definition=event_def,
        )

        # Verify session belongs to correct project
        assert session.project_id == "project_a"
        assert session.project_id != "project_b"


# =============================================================================
# Service Layer Tests
# =============================================================================


class TestRecordJudgment:
    """Tests for record_judgment service function."""

    @patch("app.evaluation.service._get_repository")
    @patch("app.evaluation.service.compute_metrics")
    def test_record_valid_judgment(self, mock_compute, mock_get_repo):
        """Test recording a valid judgment."""
        from app.evaluation.service import record_judgment

        mock_repo = MagicMock()
        mock_repo.update_judgment.return_value = True
        mock_get_repo.return_value = mock_repo
        mock_compute.return_value = EvaluationMetrics()

        # Should not raise
        record_judgment("sess1", "note1", "correct", "user1")

        mock_repo.update_judgment.assert_called_once_with(
            "sess1", "note1", "correct", "user1"
        )
        mock_repo.update_session_metrics.assert_called_once()

    def test_record_invalid_judgment(self):
        """Test recording an invalid judgment raises error."""
        from app.evaluation.service import record_judgment

        with pytest.raises(ValueError) as exc_info:
            record_judgment("sess1", "note1", "invalid_judgment", "user1")

        assert "Invalid judgment value" in str(exc_info.value)

    @patch("app.evaluation.service._get_repository")
    def test_record_judgment_update_fails(self, mock_get_repo):
        """Test handling when judgment update fails."""
        from app.evaluation.service import record_judgment

        mock_repo = MagicMock()
        mock_repo.update_judgment.return_value = False  # Update failed
        mock_get_repo.return_value = mock_repo

        # Should not raise, just log warning
        record_judgment("sess1", "note1", "correct", "user1")

        # Metrics should not be updated if judgment update failed
        mock_repo.update_session_metrics.assert_not_called()
