"""Tests for LLM-powered search pattern generation."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(content: str):
    """Build a mock LiteLLM response."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestPatternGenerator:
    async def test_generates_patterns_from_description(self):
        """LLM should generate keywords, regex, and exclusion patterns."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "keywords": ["troponin", "MI", "myocardial infarction"],
                "regex_patterns": [r"troponin.*(?:elevated|positive)"],
                "exclusion_patterns": [r"rule.?out", "family history"],
            }))

            from app.pipeline.pattern_generator import generate_search_patterns

            result = await generate_search_patterns(
                event_name="Myocardial Infarction",
                description="Confirmed MI",
                include_criteria="Troponin elevation, ECG changes",
                exclude_criteria="Rule-outs, family history",
                llm_provider="ollama",
                llm_model="llama3",
            )
            assert len(result["keywords"]) >= 2
            assert len(result["regex_patterns"]) >= 1
            assert len(result["exclusion_patterns"]) >= 1
            mock_llm.assert_called_once()

    async def test_invalid_regex_filtered_out(self):
        """Regex patterns that don't compile should be filtered out."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "keywords": ["troponin"],
                "regex_patterns": [r"troponin.*elevated", r"[invalid(regex"],
                "exclusion_patterns": [],
            }))

            from app.pipeline.pattern_generator import generate_search_patterns

            result = await generate_search_patterns(
                event_name="MI",
                description="MI",
                include_criteria="x",
                exclude_criteria="",
                llm_provider="ollama",
                llm_model="llama3",
            )
            # Only the valid regex should survive
            assert len(result["regex_patterns"]) == 1
            assert result["regex_patterns"][0] == r"troponin.*elevated"

    async def test_extracts_json_from_markdown_block(self):
        """Handle LLM responses wrapped in ```json code blocks."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            content = '```json\n{"keywords": ["stemi"], "regex_patterns": [], "exclusion_patterns": []}\n```'
            mock_llm.return_value = _mock_response(content)

            from app.pipeline.pattern_generator import generate_search_patterns

            result = await generate_search_patterns(
                event_name="STEMI",
                description="STEMI",
                include_criteria="x",
                exclude_criteria="",
                llm_provider="ollama",
                llm_model="llama3",
            )
            assert result["keywords"] == ["stemi"]

    async def test_llm_error_raises(self):
        """LLM errors should propagate as ValueError."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Connection refused")

            from app.pipeline.pattern_generator import generate_search_patterns

            with pytest.raises(ValueError, match="Pattern generation failed"):
                await generate_search_patterns(
                    event_name="MI",
                    description="MI",
                    include_criteria="x",
                    exclude_criteria="",
                    llm_provider="ollama",
                    llm_model="llama3",
                )

    async def test_malformed_json_raises(self):
        """Non-JSON LLM response should raise ValueError."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response("I cannot generate patterns for this.")

            from app.pipeline.pattern_generator import generate_search_patterns

            with pytest.raises(ValueError, match="parse"):
                await generate_search_patterns(
                    event_name="MI",
                    description="MI",
                    include_criteria="x",
                    exclude_criteria="",
                    llm_provider="ollama",
                    llm_model="llama3",
                )

    async def test_passes_provider_config_to_litellm(self):
        """Verify provider/model/api_base are correctly passed to litellm."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "keywords": ["x"], "regex_patterns": [], "exclusion_patterns": [],
            }))

            from app.pipeline.pattern_generator import generate_search_patterns

            await generate_search_patterns(
                event_name="MI",
                description="MI",
                include_criteria="x",
                exclude_criteria="",
                llm_provider="ollama",
                llm_model="llama3",
                llm_api_base="http://localhost:11434",
            )

            call_kwargs = mock_llm.call_args
            assert call_kwargs.kwargs["model"] == "ollama/llama3"
            assert call_kwargs.kwargs["api_base"] == "http://localhost:11434"


class TestGeneratePatternsAPI:
    async def test_generate_patterns_endpoint(self, client):
        """POST /events/{eid}/generate-patterns updates the EventConfig."""
        from tests.test_pipeline_api import register_and_login, create_project, EVENT_CONFIG_BODY

        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        eid = create_resp.json()["id"]

        with patch("app.pipeline.pattern_generator.generate_search_patterns", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {
                "keywords": ["troponin", "MI"],
                "regex_patterns": [r"troponin.*elevated"],
                "exclusion_patterns": [r"rule.?out"],
            }

            resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/generate-patterns",
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["search_patterns"]["keywords"] == ["troponin", "MI"]
            mock_gen.assert_called_once()

    async def test_generate_patterns_committed_config_rejected(self, client):
        """Cannot generate patterns for a committed config."""
        from tests.test_pipeline_api import register_and_login, create_project, EVENT_CONFIG_BODY

        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        eid = create_resp.json()["id"]
        await client.post(f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit", json={})

        with patch("app.pipeline.pattern_generator.generate_search_patterns", new_callable=AsyncMock) as mock_gen:
            resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/generate-patterns",
            )
            assert resp.status_code == 400
            mock_gen.assert_not_called()
