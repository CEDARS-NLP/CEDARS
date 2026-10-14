"""Attempt-scoped REST API for version-2 evaluation sessions."""

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.evaluation import query_first as workflow
from app.evaluation.models import EvaluationAttempt, SearchMatch
from app.evaluation.schemas import EventConfigRequest, SubmitJudgmentRequest
from app.pipeline.models import PipelineRun, PipelineRunStatus

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/v2",
    tags=["evaluation-v2"],
)
READ = Depends(require_project_role("admin", "annotator", "viewer"))
ADMIN = Depends(require_project_role("admin"))
REVIEW = Depends(require_project_role("admin", "annotator"))


class QueryRow(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    type: Literal["include", "exclude"] = "include"


class QueriesRequest(BaseModel):
    search_queries: list[QueryRow] = Field(min_length=1, max_length=50)
    exclude_negated: bool = True


class QueryRequest(BaseModel):
    query_id: str


class LLMRequest(QueryRequest):
    prompt_revision_id: str


class AttemptRequest(BaseModel):
    attempt_id: str


async def persist(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Concurrent revision or activation; retry the request") from exc


@router.get("/state")
async def get_state(
    project_id: str, session_id: str, db: AsyncSession = Depends(get_session), _user: User = READ
):
    session = await workflow.owned_session(db, project_id, session_id)
    return await workflow.state(db, session)


@router.put("/queries")
async def put_queries(
    project_id: str,
    session_id: str,
    body: QueriesRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    query = await workflow.save_query(
        db,
        session,
        [row.model_dump() for row in body.search_queries],
        body.exclude_negated,
        user.id,
    )
    await persist(db)
    return workflow.query_dict(query)


@router.put("/prompt")
async def put_prompt(
    project_id: str,
    session_id: str,
    body: EventConfigRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    prompt = await workflow.save_prompt(db, session, body.model_dump(), user.id)
    await persist(db)
    return workflow.prompt_dict(prompt)


async def start(
    project_id: str,
    session_id: str,
    query_id: str,
    db: AsyncSession,
    user: User,
    *,
    prompt_id: str | None = None,
    scope: str = "sample",
) -> dict:
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    attempt = await workflow.create_attempt(
        db, session, query_id, user.id, prompt_id=prompt_id, scope=scope
    )
    await persist(db)
    await workflow.dispatch(db, attempt)
    await db.refresh(attempt)
    return await workflow.attempt_dict(db, attempt)


@router.post("/preview")
async def preview(
    project_id: str,
    session_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    attempt = await workflow.create_attempt(db, session, body.query_id, user.id)
    await persist(db)
    await workflow.execute_attempt(db, attempt.id)
    await db.refresh(attempt)
    return await workflow.attempt_dict(db, attempt)


@router.post("/run-llm")
async def run_llm(
    project_id: str,
    session_id: str,
    body: LLMRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    return await start(
        project_id, session_id, body.query_id, db, user, prompt_id=body.prompt_revision_id
    )


@router.post("/run-all")
async def run_all(
    project_id: str,
    session_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    return await start(project_id, session_id, body.query_id, db, user, scope="full")


@router.post("/commit")
async def commit(
    project_id: str,
    session_id: str,
    body: AttemptRequest,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    attempt = await workflow.commit_attempt(db, session, body.attempt_id, user.id)
    await persist(db)
    await workflow.dispatch(db, attempt)
    await db.refresh(attempt)
    return await workflow.attempt_dict(db, attempt)


@router.get("/attempts/{attempt_id}")
async def get_attempt(
    project_id: str,
    session_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = READ,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    matches = (
        (await db.execute(select(SearchMatch).where(col(SearchMatch.attempt_id) == attempt.id)))
        .scalars()
        .all()
    )
    return {
        **await workflow.attempt_dict(db, attempt),
        "results": await workflow.results(db, attempt),
        "matches": [match.model_dump() for match in matches],
    }


@router.get("/attempts/{attempt_id}/matches")
async def get_matches(
    project_id: str,
    session_id: str,
    attempt_id: str,
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _user: User = READ,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    return await workflow.matched_notes(db, session, attempt, page, page_size)


@router.get("/attempts/{attempt_id}/results")
async def get_results(
    project_id: str,
    session_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = READ,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    return await workflow.results(db, attempt)


@router.post("/attempts/{attempt_id}/results/{result_id}/judge")
async def post_judgment(
    project_id: str,
    session_id: str,
    attempt_id: str,
    result_id: int,
    body: SubmitJudgmentRequest,
    db: AsyncSession = Depends(get_session),
    user: User = REVIEW,
):
    session = await workflow.owned_session(db, project_id, session_id, writable=True)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    if attempt.mode != "llm" or attempt.scope != "sample" or attempt.status != "completed":
        raise HTTPException(409, "Only completed sample LLM attempts can be judged")
    row = await workflow.judge(
        db, attempt, result_id, body.judgment, body.event_date_override, user.id
    )
    await persist(db)
    return row.model_dump(exclude={"input_snapshot"}, warnings=False)


@router.post("/attempts/{attempt_id}/retry")
async def retry(
    project_id: str,
    session_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    if session.status == "discarded":
        raise HTTPException(409, "This session is read-only")
    if attempt.status not in ("queued", "failed", "running"):
        raise HTTPException(409, "Only unfinished attempts can be retried")
    await persist(db)
    await workflow.dispatch(db, attempt)
    await db.refresh(attempt)
    return await workflow.attempt_dict(db, attempt)


@router.post("/attempts/{attempt_id}/cancel")
async def cancel(
    project_id: str,
    session_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    if attempt.status not in ("queued", "running"):
        raise HTTPException(409, "Only active attempts can be cancelled")
    changed = await db.execute(
        update(EvaluationAttempt)
        .where(
            col(EvaluationAttempt.id) == attempt.id,
            col(EvaluationAttempt.status).in_(("queued", "running")),
        )
        .values(status="cancelled", claim_token=None, updated_at=workflow.now_utc())
    )
    if not cast(CursorResult[Any], changed).rowcount:
        raise HTTPException(409, "Only active attempts can be cancelled")
    await db.refresh(attempt)
    run = (
        await db.execute(select(PipelineRun).where(col(PipelineRun.attempt_id) == attempt.id))
    ).scalar_one_or_none()
    if run:
        run.is_cancelled = True
        run.status = PipelineRunStatus.CANCELLED
        db.add(run)
    await persist(db)
    return await workflow.attempt_dict(db, attempt)


@router.post("/attempts/{attempt_id}/resume")
async def resume(
    project_id: str,
    session_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = ADMIN,
):
    session = await workflow.owned_session(db, project_id, session_id)
    attempt = await workflow.owned_attempt(db, session, attempt_id)
    if session.status == "discarded" or attempt.status != "cancelled":
        raise HTTPException(409, "Only cancelled attempts in a retained session can be resumed")
    changed = await db.execute(
        update(EvaluationAttempt)
        .where(
            col(EvaluationAttempt.id) == attempt.id,
            col(EvaluationAttempt.status) == "cancelled",
        )
        .values(status="queued", claim_token=None, updated_at=workflow.now_utc())
    )
    if not cast(CursorResult[Any], changed).rowcount:
        raise HTTPException(409, "Only cancelled attempts in a retained session can be resumed")
    await db.refresh(attempt)
    run = (
        await db.execute(select(PipelineRun).where(col(PipelineRun.attempt_id) == attempt.id))
    ).scalar_one_or_none()
    if run:
        run.is_cancelled = False
        run.status = PipelineRunStatus.QUEUED
        db.add(run)
    await persist(db)
    await workflow.dispatch(db, attempt)
    await db.refresh(attempt)
    return await workflow.attempt_dict(db, attempt)
