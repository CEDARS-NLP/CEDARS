"""Tests for the shared LiteLLM client plumbing."""

from unittest.mock import AsyncMock, patch

import pytest

from app.llm.client import (
    build_connection_kwargs,
    build_litellm_model,
    complete,
    supports_temperature,
)


class TestSupportsTemperature:
    """Claude's newest families reject sampling params with a 400."""

    @pytest.mark.parametrize(
        "model",
        [
            # First-party IDs
            "claude-sonnet-5",
            "claude-opus-5",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-fable-5",
            "claude-fable-5-1",
            # Bedrock cross-region inference profile IDs
            "us.anthropic.claude-sonnet-5",
            "us.anthropic.claude-opus-5",
            "global.anthropic.claude-fable-5-1",
            "eu.anthropic.claude-opus-4-8",
            # Bedrock on-demand IDs (no region prefix)
            "anthropic.claude-sonnet-5",
        ],
    )
    def test_rejects_temperature(self, model):
        assert supports_temperature(model) is False

    @pytest.mark.parametrize(
        "model",
        [
            # Older Claude families still accept temperature
            "claude-haiku-4-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "us.anthropic.claude-opus-4-6-v1",
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            # Non-Claude models are unaffected
            "gpt-4o-mini",
            "llama3",
            "mistral",
            "",
        ],
    )
    def test_accepts_temperature(self, model):
        assert supports_temperature(model) is True

    def test_sonnet_4_5_not_confused_with_sonnet_5(self):
        """``claude-sonnet-4-5`` must not match the ``claude-sonnet-5`` family."""
        assert supports_temperature("claude-sonnet-4-5") is True


class TestCompleteParams:
    """``complete`` decides whether temperature goes on the wire."""

    @pytest.fixture
    def acompletion(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
            yield mock

    async def test_omits_temperature_for_sonnet_5(self, acompletion):
        await complete(
            provider="bedrock",
            model="us.anthropic.claude-sonnet-5",
            messages=[{"role": "user", "content": "hi"}],
        )
        kwargs = acompletion.call_args.kwargs
        assert "temperature" not in kwargs
        assert kwargs["model"] == "bedrock/us.anthropic.claude-sonnet-5"

    async def test_sends_temperature_for_haiku(self, acompletion):
        await complete(
            provider="bedrock",
            model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.0,
        )
        assert acompletion.call_args.kwargs["temperature"] == 0.0

    async def test_always_sets_drop_params(self, acompletion):
        """LiteLLM drops params it knows a model rejects instead of raising."""
        await complete(
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert acompletion.call_args.kwargs["drop_params"] is True

    async def test_caller_can_override_drop_params(self, acompletion):
        await complete(
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            drop_params=False,
        )
        assert acompletion.call_args.kwargs["drop_params"] is False

    async def test_extra_kwargs_pass_through(self, acompletion):
        await complete(
            provider="openai",
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=128,
        )
        assert acompletion.call_args.kwargs["max_tokens"] == 128


class TestJsonModeParam:
    """``response_format`` only reaches providers that implement it natively.

    On Bedrock, LiteLLM emulates it with a forced tool call and returns a literal
    "{}" — which parsed cleanly and made every classification a default answer.
    """

    @pytest.fixture
    def acompletion(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
            yield mock

    @pytest.mark.parametrize("provider", ["bedrock", "anthropic"])
    async def test_dropped_for_emulating_providers(self, acompletion, provider):
        await complete(
            provider=provider,
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )
        assert "response_format" not in acompletion.call_args.kwargs

    @pytest.mark.parametrize("provider", ["openai", "ollama", "vllm", "lmstudio"])
    async def test_kept_for_native_providers(self, acompletion, provider):
        await complete(
            provider=provider,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )
        assert acompletion.call_args.kwargs["response_format"] == {"type": "json_object"}


class TestBuildLitellmModel:
    def test_bedrock_prefix(self):
        assert (
            build_litellm_model("bedrock", "us.anthropic.claude-sonnet-5")
            == "bedrock/us.anthropic.claude-sonnet-5"
        )

    def test_bedrock_takes_no_connection_kwargs(self):
        assert build_connection_kwargs("bedrock", "http://x", "key") == {}
