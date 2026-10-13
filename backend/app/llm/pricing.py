"""Ballpark LLM pricing for user-facing cost estimates.

These are list prices in USD per 1M tokens, copied by hand and rounded; they
drift. Use them to tell a user "about $2 or about $200", never for billing.
Bedrock bills Claude at its own (usually similar) rates, so Claude models
share one row whichever provider serves them. Self-hosted providers (ollama,
vllm) cost nothing per token and return ``None`` from ``estimate_cost``.
"""

# (substring of the lowercased model id, (input $/1M, output $/1M)).
# First match wins, so list more specific names before general ones.
_PRICES: list[tuple[str, tuple[float, float]]] = [
    ("fable", (10.0, 50.0)),
    ("opus-5-5", (4.0, 20.0)),
    ("opus", (5.0, 25.0)),
    ("sonnet-4", (3.0, 15.0)),
    ("sonnet", (2.0, 10.0)),
    ("haiku", (1.0, 5.0)),
    ("gpt-4o-mini", (0.15, 0.60)),
    ("gpt-4o", (2.50, 10.0)),
]

_SELF_HOSTED = {"ollama", "vllm"}


def estimate_cost(
    provider: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """Return an approximate USD cost, or ``None`` when the price is unknown.

    ``None`` means "don't show a number" — a free local model and an
    unrecognised model are both reported as no estimate rather than $0.
    """
    if not model or (provider or "").lower() in _SELF_HOSTED:
        return None
    name = model.lower()
    for needle, (price_in, price_out) in _PRICES:
        if needle in name:
            return (prompt_tokens * price_in + completion_tokens * price_out) / 1e6
    return None
