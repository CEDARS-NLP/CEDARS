"""Tests for the predictors module."""

import pytest
from unittest.mock import patch, MagicMock

from app.predictors import (
    BasePredictor,
    PredictionResult,
    PredictorError,
    PredictorType,
    LLMProvider,
    LLMConfig,
    EventDefinition,
    PredictorConfig,
    PinesPredictor,
    get_predictor,
)


class TestPredictionResult:
    """Tests for PredictionResult dataclass."""

    def test_create_result(self):
        result = PredictionResult(
            score=0.85,
            label=1,
            model="test-model",
            reasoning="Test reasoning"
        )
        assert result.score == 0.85
        assert result.label == 1
        assert result.model == "test-model"
        assert result.reasoning == "Test reasoning"

    def test_result_without_reasoning(self):
        result = PredictionResult(score=0.5, label=0, model="pines")
        assert result.reasoning is None


class TestPredictorConfig:
    """Tests for predictor configuration models."""

    def test_event_definition(self):
        event = EventDefinition(
            name="Myocardial Infarction",
            description="Heart attack",
            include_criteria="Positive troponin",
            exclude_criteria="Rule-out"
        )
        assert event.name == "Myocardial Infarction"
        assert event.description == "Heart attack"

    def test_llm_config(self):
        config = LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            api_key_env="OPENAI_API_KEY"
        )
        assert config.provider == LLMProvider.OPENAI
        assert config.model == "gpt-4o"
        assert config.timeout == 60
        assert config.temperature == 0.0

    def test_predictor_config_pines(self):
        config = PredictorConfig(
            predictor_type=PredictorType.PINES,
            pines_url="http://pines:8036"
        )
        assert config.predictor_type == PredictorType.PINES
        assert config.pines_url == "http://pines:8036"
        assert config.threshold == 0.95

    def test_predictor_config_llm(self):
        llm_config = LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-sonnet-4-20250514"
        )
        event = EventDefinition(
            name="Test Event",
            description="Test",
            include_criteria="Include",
            exclude_criteria="Exclude"
        )
        config = PredictorConfig(
            predictor_type=PredictorType.LLM,
            llm_config=llm_config,
            event_definition=event
        )
        assert config.predictor_type == PredictorType.LLM
        assert config.llm_config.provider == LLMProvider.ANTHROPIC


class TestPinesPredictor:
    """Tests for PinesPredictor."""

    @pytest.fixture
    def pines_predictor(self):
        return PinesPredictor(pines_url="http://localhost:8036")

    def test_init(self, pines_predictor):
        assert pines_predictor.pines_url == "http://localhost:8036"
        assert pines_predictor.timeout == 3600

    @patch("app.predictors.pines.requests.post")
    def test_predict_positive(self, mock_post, pines_predictor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "prediction": {"score": 0.95, "label": 1},
            "model": "pines-v1"
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = pines_predictor.predict("Patient has chest pain")

        assert result.score == 0.95
        assert result.label == 1
        assert result.model == "pines-v1"
        mock_post.assert_called_once()

    @patch("app.predictors.pines.requests.post")
    def test_predict_negative_inverts_score(self, mock_post, pines_predictor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "prediction": {"score": 0.9, "label": 0},
            "model": "pines-v1"
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = pines_predictor.predict("No chest pain")

        # Score should be inverted when label is 0
        assert result.score == 0.1  # 1 - 0.9
        assert result.label == 0

    @patch("app.predictors.pines.requests.post")
    def test_predict_connection_error(self, mock_post, pines_predictor):
        from requests.exceptions import ConnectionError
        mock_post.side_effect = ConnectionError("Connection refused")

        with pytest.raises(PredictorError) as exc_info:
            pines_predictor.predict("Test text")

        assert "Cannot connect to PINES" in str(exc_info.value)

    @patch("app.predictors.pines.requests.get")
    def test_healthcheck_healthy(self, mock_get, pines_predictor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "Healthy",
            "message": "Current Model: pines-v1"
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        assert pines_predictor.healthcheck() is True

    @patch("app.predictors.pines.requests.get")
    def test_healthcheck_unhealthy(self, mock_get, pines_predictor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "Unhealthy"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        assert pines_predictor.healthcheck() is False


class TestGetPredictor:
    """Tests for the predictor factory function."""

    def test_get_pines_predictor_from_config(self):
        config = PredictorConfig(
            predictor_type=PredictorType.PINES,
            pines_url="http://pines:8036"
        )
        predictor = get_predictor(predictor_config=config)

        assert isinstance(predictor, PinesPredictor)
        assert predictor.pines_url == "http://pines:8036"

    def test_get_predictor_missing_pines_url(self):
        config = PredictorConfig(
            predictor_type=PredictorType.PINES,
            pines_url=None
        )

        with pytest.raises(PredictorError) as exc_info:
            get_predictor(predictor_config=config)

        assert "PINES URL is required" in str(exc_info.value)

    def test_get_predictor_from_project_info_pines(self):
        project_info = {
            "predictor_type": "pines",
            "pines_url": "http://pines:8036"
        }
        predictor = get_predictor(project_info=project_info)

        assert isinstance(predictor, PinesPredictor)

    def test_get_predictor_from_project_info_legacy(self):
        # Test backwards compatibility with legacy nlp_apply=True
        project_info = {
            "nlp_apply": True,
            "pines_url": "http://pines:8036"
        }
        predictor = get_predictor(project_info=project_info)

        assert isinstance(predictor, PinesPredictor)

    def test_get_predictor_no_config(self):
        with pytest.raises(PredictorError) as exc_info:
            get_predictor()

        assert "must be provided" in str(exc_info.value)


class TestLLMPredictor:
    """Tests for LLMPredictor (with mocked LiteLLM)."""

    @pytest.fixture
    def llm_config(self):
        return LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            api_key_env="OPENAI_API_KEY"
        )

    @pytest.fixture
    def event_definition(self):
        return EventDefinition(
            name="Myocardial Infarction",
            description="Heart attack diagnosis",
            include_criteria="Positive troponin, ECG changes",
            exclude_criteria="Rule-out, family history"
        )

    @patch("app.predictors.llm.LITELLM_AVAILABLE", True)
    @patch("app.predictors.llm.completion")
    def test_predict_positive(self, mock_completion, llm_config, event_definition):
        from app.predictors.llm import LLMPredictor

        # Mock LiteLLM response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"contains_event": true, "confidence": 0.95, "reasoning": "Test"}'
                )
            )
        ]
        mock_completion.return_value = mock_response

        predictor = LLMPredictor(config=llm_config, event_definition=event_definition)
        result = predictor.predict("Patient diagnosed with MI")

        assert result.score == 0.95
        assert result.label == 1
        assert result.reasoning == "Test"

    @patch("app.predictors.llm.LITELLM_AVAILABLE", True)
    @patch("app.predictors.llm.completion")
    def test_predict_negative(self, mock_completion, llm_config, event_definition):
        from app.predictors.llm import LLMPredictor

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"contains_event": false, "confidence": 0.9, "reasoning": "No event"}'
                )
            )
        ]
        mock_completion.return_value = mock_response

        predictor = LLMPredictor(config=llm_config, event_definition=event_definition)
        result = predictor.predict("Normal checkup")

        # Score inverted for negative: 1 - 0.9 = 0.1
        assert result.score == 0.1
        assert result.label == 0

    @patch("app.predictors.llm.LITELLM_AVAILABLE", True)
    @patch("app.predictors.llm.completion")
    def test_predict_handles_markdown_json(self, mock_completion, llm_config, event_definition):
        from app.predictors.llm import LLMPredictor

        # LLM sometimes wraps JSON in markdown code blocks
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='```json\n{"contains_event": true, "confidence": 0.8, "reasoning": "Test"}\n```'
                )
            )
        ]
        mock_completion.return_value = mock_response

        predictor = LLMPredictor(config=llm_config, event_definition=event_definition)
        result = predictor.predict("Test note")

        assert result.score == 0.8
        assert result.label == 1

    @patch("app.predictors.llm.LITELLM_AVAILABLE", False)
    def test_raises_when_litellm_not_available(self, llm_config, event_definition):
        # Need to reload the module to pick up the patched LITELLM_AVAILABLE
        # This test verifies the error message is correct
        from app.predictors.llm import LLMPredictor, LITELLM_AVAILABLE

        if not LITELLM_AVAILABLE:
            with pytest.raises(PredictorError) as exc_info:
                LLMPredictor(config=llm_config, event_definition=event_definition)

            assert "LiteLLM is not installed" in str(exc_info.value)
