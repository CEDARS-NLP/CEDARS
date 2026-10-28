"""Project-level LLM usage report."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.dependencies import get_project_db_session
from app.common.utils import now_utc
from app.dependencies import require_project_role
from app.llm.usage import LlmUsage

router = APIRouter(prefix="/api/v1/projects/{project_id}/llm-usage", tags=["llm-usage"])


class UsageTotals(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    # Sum over priced calls only; null when none were priced (e.g. local models).
    estimated_cost: float | None
    unpriced_calls: int


class UsageGroup(UsageTotals):
    key: str


class UsageDay(BaseModel):
    date: str
    tokens: int
    estimated_cost: float | None


class UsageReport(BaseModel):
    days: int
    totals: UsageTotals
    by_source: list[UsageGroup]
    by_model: list[UsageGroup]
    by_day: list[UsageDay]


def _aggregates():
    return (
        func.count(LlmUsage.id),
        func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
        func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
        func.sum(LlmUsage.estimated_cost),
        func.count(LlmUsage.id) - func.count(LlmUsage.estimated_cost),
    )


def _totals(row) -> dict:
    calls, prompt, completion, cost, unpriced = row
    return {
        "calls": calls,
        "prompt_tokens": int(prompt),
        "completion_tokens": int(completion),
        "estimated_cost": float(cost) if cost is not None else None,
        "unpriced_calls": unpriced,
    }


@router.get("", response_model=UsageReport)
async def llm_usage_report(
    project_id: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_project_db_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Tokens and estimated cost for every LLM call the project made in the window."""
    since = now_utc() - timedelta(days=days)
    in_window = (LlmUsage.project_id == project_id, LlmUsage.created_at >= since)

    totals = (await db.execute(select(*_aggregates()).where(*in_window))).one()

    async def grouped(column) -> list[dict]:
        rows = (
            await db.execute(
                select(column, *_aggregates())
                .where(*in_window)
                .group_by(column)
                .order_by(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens).desc())
            )
        ).all()
        return [{"key": r[0] or "unknown", **_totals(r[1:])} for r in rows]

    day = func.date(LlmUsage.created_at)
    day_rows = (
        await db.execute(
            select(
                day,
                func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens),
                func.sum(LlmUsage.estimated_cost),
            )
            .where(*in_window)
            .group_by(day)
            .order_by(day)
        )
    ).all()

    return UsageReport(
        days=days,
        totals=_totals(totals),
        by_source=await grouped(LlmUsage.source),
        by_model=await grouped(LlmUsage.model),
        by_day=[
            {"date": str(d), "tokens": int(t or 0), "estimated_cost": float(c) if c is not None else None}
            for d, t, c in day_rows
        ],
    )
