"""Per-project ledger of LLM token usage.

Every model call goes through ``app.llm.client.complete``, which has no database
and no project. A caller that knows the project opens a ``UsageScope``; while it
is active ``complete`` records each call's token counts into it, and the caller
flushes the scope into ``llm_usage`` with the rest of its transaction. Rows are
append-only and carry the cost at the prices of the day, so later price changes
never rewrite history.
"""

from contextvars import ContextVar
from datetime import datetime

from sqlalchemy import Column, DateTime, Index
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc
from app.llm.pricing import estimate_cost


class LlmUsage(SQLModel, table=True):
    """One model call (or one patient's call) and what it cost in tokens."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_project_created", "project_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    # What triggered the call: query_suggestion, evaluation_sample, pipeline_run,
    # predictor_test, bulk_prediction, pattern_generation.
    source: str = Field(max_length=40)
    # Session / pipeline run / job the call belongs to, when there is one.
    ref_id: str | None = Field(default=None, max_length=64)
    provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    # None when the model has no per-token price (local models, unknown names).
    estimated_cost: float | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=lambda: now_utc()),
    )


def add_usage(
    db: AsyncSession,
    *,
    project_id: str,
    source: str,
    provider: str | None,
    model: str | None,
    usage: dict | None,
    ref_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Add one ledger row to the session for a call whose token usage is in hand."""
    if not usage:
        return
    prompt = usage.get("prompt_tokens", 0) or 0
    completion = usage.get("completion_tokens", 0) or 0
    db.add(
        LlmUsage(
            project_id=project_id,
            user_id=user_id,
            source=source,
            ref_id=ref_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            estimated_cost=estimate_cost(provider, model, prompt, completion),
        )
    )


_current: ContextVar["UsageScope | None"] = ContextVar("llm_usage_scope", default=None)


class UsageScope:
    """Collects token usage for every ``complete`` call made while it is active."""

    def __init__(
        self,
        project_id: str,
        source: str,
        *,
        ref_id: str | None = None,
        user_id: str | None = None,
    ):
        self.project_id = project_id
        self.source = source
        self.ref_id = ref_id
        self.user_id = user_id
        self._calls: list[tuple[str | None, str | None, dict]] = []
        self._token = None

    def __enter__(self) -> "UsageScope":
        self._token = _current.set(self)
        return self

    def __exit__(self, *exc) -> None:
        _current.reset(self._token)

    def record(self, provider: str | None, model: str | None, usage: dict | None) -> None:
        if usage:
            self._calls.append((provider, model, usage))

    def flush(self, db: AsyncSession) -> int:
        """Add one ledger row per recorded call; the caller commits. Returns the row count."""
        calls, self._calls = self._calls, []
        for provider, model, usage in calls:
            add_usage(
                db,
                project_id=self.project_id,
                source=self.source,
                provider=provider,
                model=model,
                usage=usage,
                ref_id=self.ref_id,
                user_id=self.user_id,
            )
        return len(calls)


def current_scope() -> UsageScope | None:
    return _current.get()
