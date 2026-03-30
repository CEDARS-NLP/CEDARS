"""Tests for LLM note classifier (single-call-per-patient, Decision #32)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(content: str):
    """Build a mock LiteLLM response."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    return resp


def _mock_event_config():
    cfg = MagicMock()
    cfg.name = "Myocardial Infarction"
    cfg.description = "Confirmed MI event"
    cfg.include_criteria = "Troponin elevation, ECG changes"
    cfg.exclude_criteria = "Rule-out, family history"
    cfg.llm_provider = "ollama"
    cfg.llm_model = "llama3"
    cfg.llm_api_base = None
    return cfg


class TestClassifyPatient:
    async def test_classifies_positive(self):
        """Single call with excerpts returns positive classification."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "event_detected": True,
                "confidence": 0.92,
                "reasoning": "Troponin elevated, ECG shows ST changes",
            }))

            from app.pipeline.classifier import classify_patient

            result = await classify_patient(
                excerpts=[
                    {"note_id": "n1", "text": "Troponin I elevated at 2.4 ng/mL"},
                    {"note_id": "n2", "text": "ECG shows ST elevation in leads V1-V4"},
                ],
                event_config=_mock_event_config(),
            )
            assert result.label == "positive"
            assert result.confidence == 0.92
            assert "Troponin" in result.reasoning
            mock_llm.assert_called_once()

    async def test_classifies_negative(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "event_detected": False,
                "confidence": 0.15,
                "reasoning": "No evidence of MI in the excerpts",
            }))

            from app.pipeline.classifier import classify_patient

            result = await classify_patient(
                excerpts=[{"note_id": "n1", "text": "Normal labs, no issues"}],
                event_config=_mock_event_config(),
            )
            assert result.label == "negative"
            assert result.confidence == 0.15

    async def test_includes_all_excerpts_in_prompt(self):
        """Verify all excerpts are included in the single LLM call."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "event_detected": True, "confidence": 0.8, "reasoning": "Found",
            }))

            from app.pipeline.classifier import classify_patient

            await classify_patient(
                excerpts=[
                    {"note_id": "n1", "text": "Excerpt one"},
                    {"note_id": "n2", "text": "Excerpt two"},
                    {"note_id": "n3", "text": "Excerpt three"},
                ],
                event_config=_mock_event_config(),
            )

            call_args = mock_llm.call_args
            user_msg = call_args.kwargs["messages"][1]["content"]
            assert "Excerpt one" in user_msg
            assert "Excerpt two" in user_msg
            assert "Excerpt three" in user_msg

    async def test_token_usage_tracked(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "event_detected": True, "confidence": 0.9, "reasoning": "Found",
            }))

            from app.pipeline.classifier import classify_patient

            result = await classify_patient(
                excerpts=[{"note_id": "n1", "text": "troponin elevated"}],
                event_config=_mock_event_config(),
            )
            assert result.token_usage is not None
            assert result.token_usage["prompt_tokens"] == 100
            assert result.token_usage["total_tokens"] == 150

    async def test_llm_error_raises(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Connection refused")

            from app.pipeline.classifier import classify_patient

            with pytest.raises(ValueError, match="Classification failed"):
                await classify_patient(
                    excerpts=[{"note_id": "n1", "text": "troponin"}],
                    event_config=_mock_event_config(),
                )

    async def test_malformed_json_raises(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response("I can't classify this.")

            from app.pipeline.classifier import classify_patient

            with pytest.raises(ValueError, match="parse"):
                await classify_patient(
                    excerpts=[{"note_id": "n1", "text": "troponin"}],
                    event_config=_mock_event_config(),
                )

    async def test_empty_excerpts_returns_negative(self):
        from app.pipeline.classifier import classify_patient

        result = await classify_patient(
            excerpts=[],
            event_config=_mock_event_config(),
        )
        assert result.label == "negative"
        assert result.confidence == 0.0

    async def test_markdown_json_response(self):
        """Handle LLM responses wrapped in ```json code blocks."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            content = '```json\n{"event_detected": true, "confidence": 0.88, "reasoning": "Found MI"}\n```'
            mock_llm.return_value = _mock_response(content)

            from app.pipeline.classifier import classify_patient

            result = await classify_patient(
                excerpts=[{"note_id": "n1", "text": "MI confirmed"}],
                event_config=_mock_event_config(),
            )
            assert result.label == "positive"
            assert result.confidence == 0.88
