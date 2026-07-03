"""Shared LiteLLM client plumbing.

Every LLM-backed feature (patient classification, pattern generation, query
suggestion, the LLM predictor) went through the same four steps with its own
copy of the code: build the provider-prefixed model string, build connection
kwargs (with the Bedrock/self-hosted quirks), call ``litellm.acompletion``, and
extract JSON from the response. A single fixed bug (the Bedrock ``api_base``
guard) had to be applied in four places and still missed one. This module is
the one home for that plumbing.
"""

import json
import logging
import re
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Providers that speak the OpenAI-compatible HTTP API and need an "openai/"
# LiteLLM prefix plus a "/v1" api_base suffix.
_OPENAI_COMPATIBLE = ("vllm", "lmstudio", "tgi", "openai_compatible")


def build_litellm_model(provider: str, model: str) -> str:
    """Build the LiteLLM model string.

    LiteLLM uses a ``provider/model`` format. For OpenAI-compatible endpoints
    (vLLM, LMStudio, text-generation-inference), prefix with ``openai/``.
    """
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    if provider in _OPENAI_COMPATIBLE:
        return f"openai/{model}"
    return model


def build_connection_kwargs(
    provider: str, api_base: str | None, api_key: str | None = None
) -> dict:
    """Build ``api_base``/``api_key`` kwargs for ``litellm.acompletion``.

    - Bedrock authenticates via AWS SigV4 (env/role creds) and takes no HTTP
      ``api_base`` or ``api_key`` — passing either produces an invalid URL, so
      both are ignored regardless of what is stored on the config.
    - Whitespace/quote-only ``api_base`` is treated as unset (guards against a
      stray stored value like a literal ``""`` becoming a bogus endpoint URL).
    - OpenAI-compatible providers get a ``/v1`` suffix since LiteLLM appends
      ``/chat/completions`` to ``api_base``.
    - Self-hosted providers that require *some* key but have none configured get
      a placeholder so LiteLLM doesn't raise ``AuthenticationError``. An
      explicitly configured key always wins (e.g. a gated vLLM behind a proxy).
    """
    kwargs: dict = {}
    if provider == "bedrock":
        return kwargs
    api_base = (api_base or "").strip().strip('"').strip("'").strip()
    if api_base:
        api_base = api_base.rstrip("/")
        if provider in _OPENAI_COMPATIBLE and not api_base.endswith("/v1"):
            api_base = api_base + "/v1"
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    elif provider in ("ollama", *_OPENAI_COMPATIBLE):
        kwargs["api_key"] = "no-key-required"
    return kwargs


def extract_json(content: str) -> Any:
    """Parse a JSON object or array out of a raw LLM response.

    Handles markdown code fences, prose around the JSON, and trailing commas.
    Raises ``ValueError`` if no valid JSON can be extracted.
    """
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```(?:json)?\s*", "", content)
        content = content.rstrip("`").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Find the first JSON opener and match it to its closer via depth counting,
    # so nested braces/brackets are handled correctly.
    opener = None
    start = -1
    for i, ch in enumerate(content):
        if ch in "{[":
            opener, start = ch, i
            break
    if start != -1:
        closer = "}" if opener == "{" else "]"
        depth = 0
        for i in range(start, len(content)):
            if content[i] == opener:
                depth += 1
            elif content[i] == closer:
                depth -= 1
                if depth == 0:
                    candidate = content[start : i + 1]
                    # Fix a common LLM issue: trailing commas before } or ].
                    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not parse LLM response as JSON: {content[:300]}")


def extract_token_usage(response) -> dict | None:
    """Extract a ``{prompt,completion,total}_tokens`` dict from a response."""
    usage = getattr(response, "usage", None)
    if not usage:
        return None
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


async def complete(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    api_base: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    timeout: int = 60,
    **litellm_kwargs,
):
    """Call ``litellm.acompletion`` with the shared model/connection plumbing.

    Extra keyword args (``response_format``, ``num_retries``, ``max_tokens``…)
    pass straight through to LiteLLM. Returns the raw LiteLLM response; callers
    map exceptions to their own domain errors.
    """
    return await litellm.acompletion(
        model=build_litellm_model(provider, model),
        messages=messages,
        temperature=temperature,
        timeout=timeout,
        **build_connection_kwargs(provider, api_base, api_key),
        **litellm_kwargs,
    )


async def complete_json(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    api_base: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    timeout: int = 60,
    **litellm_kwargs,
) -> tuple[Any, dict | None]:
    """Run a completion and parse JSON from it.

    Returns ``(parsed_json, token_usage)``. Raises ``ValueError`` if the
    response can't be parsed as JSON; propagates LiteLLM errors otherwise.
    """
    response = await complete(
        provider=provider,
        model=model,
        messages=messages,
        api_base=api_base,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        **litellm_kwargs,
    )
    content = response.choices[0].message.content or ""
    return extract_json(content), extract_token_usage(response)
