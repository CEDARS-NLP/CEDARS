from app.llm.pricing import estimate_cost


def test_known_models_priced_per_million_tokens():
    # Haiku: $1 in / $5 out per 1M.
    assert estimate_cost("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0", 1_000_000, 1_000_000) == 6.0
    assert estimate_cost("openai", "gpt-4o-mini", 1_000_000, 0) == 0.15


def test_specific_names_win_over_general():
    assert estimate_cost("anthropic", "claude-opus-5-5", 1_000_000, 0) == 4.0
    assert estimate_cost("anthropic", "claude-opus-5", 1_000_000, 0) == 5.0
    assert estimate_cost("openai", "gpt-4o", 1_000_000, 0) == 2.5


def test_free_or_unknown_models_have_no_estimate():
    assert estimate_cost("ollama", "claude-haiku", 1000, 1000) is None
    assert estimate_cost("openai", "mystery-model", 1000, 1000) is None
    assert estimate_cost("openai", None, 1000, 1000) is None
