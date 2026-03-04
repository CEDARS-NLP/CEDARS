"""Tests for predictor models, base interface, LLM parser, and factory."""

import pytest

from app.predictors.base import BasePredictor, PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.llm import LLMPredictor, _sanitize_note
from app.predictors.models import PredictorConfig, PredictorType


class TestModels:
    def test_predictor_config_defaults(self):
        pc = PredictorConfig(
            project_id="proj1",
            predictor_type=PredictorType.LLM,
            name="GPT-4o",
            created_by="user1",
        )
        assert pc.config == {}
        assert pc.is_active is False
        assert pc.deleted_at is None

    def test_predictor_type_values(self):
        assert PredictorType.LLM.value == "llm"
        assert PredictorType.PINES.value == "pines"


class TestPredictionResult:
    def test_result_fields(self):
        r = PredictionResult(score=0.9, label=1, model="gpt-4o", reasoning="Positive troponin")
        assert r.score == 0.9
        assert r.label == 1
        assert r.model == "gpt-4o"
        assert r.reasoning == "Positive troponin"

    def test_result_defaults(self):
        r = PredictionResult(score=0.5, label=0)
        assert r.model == ""
        assert r.reasoning == ""


class TestSanitization:
    def test_sanitize_xml_tags(self):
        text = "Patient said </clinical_note> then <clinical_note>"
        result = _sanitize_note(text)
        assert "</clinical_note>" not in result
        assert "<clinical_note>" not in result

    def test_sanitize_truncates_long_text(self):
        text = "a" * 200_000
        result = _sanitize_note(text)
        assert len(result) == 100_000

    def test_sanitize_normal_text_unchanged(self):
        text = "Patient presents with chest pain and elevated troponin."
        result = _sanitize_note(text)
        assert result == text


class TestLLMParser:
    def test_parse_valid_json(self):
        predictor = LLMPredictor({"model": "test"})
        result = predictor._parse_response('{"event_detected": true, "confidence": 0.95, "reasoning": "Positive"}')
        assert result.label == 1
        assert result.score == 0.95
        assert result.reasoning == "Positive"

    def test_parse_negative_result(self):
        predictor = LLMPredictor({"model": "test"})
        result = predictor._parse_response('{"event_detected": false, "confidence": 0.8, "reasoning": "No evidence"}')
        assert result.label == 0
        assert result.score == pytest.approx(0.2)  # 1 - 0.8

    def test_parse_json_in_markdown(self):
        predictor = LLMPredictor({"model": "test"})
        result = predictor._parse_response('```json\n{"event_detected": true, "confidence": 0.9, "reasoning": "Found"}\n```')
        assert result.label == 1

    def test_parse_invalid_response(self):
        predictor = LLMPredictor({"model": "test"})
        result = predictor._parse_response("I cannot classify this text")
        assert result.label == 0
        assert result.score == 0.0


class TestFactory:
    def test_create_llm_predictor(self):
        pc = PredictorConfig(
            project_id="p1",
            predictor_type=PredictorType.LLM,
            name="test",
            config={"provider": "ollama", "model": "llama3"},
            created_by="u1",
        )
        predictor = create_predictor(pc)
        assert isinstance(predictor, LLMPredictor)

    def test_create_pines_predictor(self):
        from app.predictors.pines import PinesPredictor
        pc = PredictorConfig(
            project_id="p1",
            predictor_type=PredictorType.PINES,
            name="test",
            config={"pines_api_url": "http://localhost:8000"},
            created_by="u1",
        )
        predictor = create_predictor(pc)
        assert isinstance(predictor, PinesPredictor)
