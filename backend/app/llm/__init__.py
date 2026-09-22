"""Shared LiteLLM client plumbing for all LLM-backed features."""

from app.llm.client import (
    build_connection_kwargs,
    build_litellm_model,
    complete,
    complete_json,
    extract_json,
    extract_token_usage,
    strip_bedrock_prefixes,
    supports_temperature,
)

__all__ = [
    "build_connection_kwargs",
    "build_litellm_model",
    "complete",
    "complete_json",
    "extract_json",
    "extract_token_usage",
    "strip_bedrock_prefixes",
    "supports_temperature",
]
