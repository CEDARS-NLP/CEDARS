"""LLM prompt evaluation system models and utilities."""

from app.evaluation.models import (
    EvaluationJudgment,
    EvaluationMetrics,
    EvaluationSession,
    LLMPrediction,
    SampleConfig,
    ValidatedPrompt,
)

from app.evaluation.service import (
    compute_metrics,
    create_session,
    get_active_validated_prompt,
    get_disagreements,
    get_next_for_review,
    get_prompts_by_project,
    get_session,
    get_sessions_by_project,
    record_judgment,
    run_predictions,
    set_active_prompt,
    validate_prompt,
)

__all__ = [
    # Models
    "EvaluationJudgment",
    "EvaluationMetrics",
    "EvaluationSession",
    "LLMPrediction",
    "SampleConfig",
    "ValidatedPrompt",
    # Service functions
    "compute_metrics",
    "create_session",
    "get_active_validated_prompt",
    "get_disagreements",
    "get_next_for_review",
    "get_prompts_by_project",
    "get_session",
    "get_sessions_by_project",
    "record_judgment",
    "run_predictions",
    "set_active_prompt",
    "validate_prompt",
]
