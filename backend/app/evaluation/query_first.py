"""Revision-owned query-first evaluation, isolated from legacy session execution."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.models import Annotation
from app.audit.models import AuditAction, AuditEntry
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.evaluation.models import (
    EvaluationAttempt,
    EvaluationSession,
    LLMPromptRevision,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)
from app.nlp.models import SearchQuery
from app.pipeline.classifier import SYSTEM_PROMPT, classify_patient
from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus
from app.projects.models import Project


async def flush(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Concurrent revision or activation; retry the request") from exc


def helper_rows(rows: list[dict]) -> list[dict]:
    return [{"query": row["query"], "query_type": row.get("type", "include")} for row in rows]


async def owned_session(
    db: AsyncSession, project_id: str, session_id: str, *, writable: bool = False
) -> EvaluationSession:
    session = (
        await db.execute(
            select(EvaluationSession)
            .where(
                col(EvaluationSession.id) == session_id,
                col(EvaluationSession.project_id) == project_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(404, "Session not found")
    if session.workflow_version != 2:
        raise HTTPException(409, "This session uses the legacy evaluation workflow")
    if writable and session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise HTTPException(409, "This session is read-only")
    return session


async def owned_query(db: AsyncSession, session: EvaluationSession, query_id: str) -> SearchQuery:
    query = await db.get(SearchQuery, query_id)
    if (
        query is None
        or query.evaluation_session_id != session.id
        or query.project_id != session.project_id
        or query.deleted_at is not None
    ):
        raise HTTPException(404, "Query revision not found in this session")
    return query


async def owned_prompt(
    db: AsyncSession, session: EvaluationSession, prompt_id: str
) -> LLMPromptRevision:
    prompt = await db.get(LLMPromptRevision, prompt_id)
    if prompt is None or prompt.session_id != session.id or prompt.project_id != session.project_id:
        raise HTTPException(404, "Prompt revision not found in this session")
    return prompt


async def owned_attempt(
    db: AsyncSession, session: EvaluationSession, attempt_id: str
) -> EvaluationAttempt:
    attempt = await db.get(EvaluationAttempt, attempt_id)
    if attempt is None or attempt.session_id != session.id:
        raise HTTPException(404, "Attempt not found in this session")
    return attempt


async def save_query(
    db: AsyncSession,
    session: EvaluationSession,
    rows: list[dict],
    exclude_negated: bool,
    actor: str,
) -> SearchQuery:
    from app.nlp.query_expression import compile_query_rows

    try:
        compiled = compile_query_rows(helper_rows(rows))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    revision = (
        await db.scalar(
            select(func.max(col(SearchQuery.revision))).where(
                col(SearchQuery.evaluation_session_id) == session.id
            )
        )
    ) or 0
    query = SearchQuery(
        project_id=session.project_id,
        evaluation_session_id=session.id,
        revision=revision + 1,
        syntax_version=2,
        source_queries=rows,
        query=compiled,
        exclude_negated=exclude_negated,
        is_active=False,
        nlp_apply=False,
        created_by=actor,
    )
    session.search_queries = rows
    db.add(query)
    db.add(session)
    await flush(db)
    return query


async def save_prompt(
    db: AsyncSession, session: EvaluationSession, fields: dict, actor: str
) -> LLMPromptRevision:
    project = await db.get(Project, session.project_id)
    if not project or not project.llm_provider or not project.llm_model:
        raise HTTPException(422, "Configure a project LLM provider and model first")
    if not fields["event_name"].strip() or not fields["event_description"].strip():
        raise HTTPException(422, "Event name and description are required")
    revision = (
        await db.scalar(
            select(func.max(col(LLMPromptRevision.revision))).where(
                col(LLMPromptRevision.session_id) == session.id
            )
        )
    ) or 0
    template = (
        f"Event to detect: {fields['event_name']}\n"
        f"Description: {fields['event_description']}\n"
        f"Include criteria: {fields['include_criteria']}\n"
        f"Exclude criteria: {fields['exclude_criteria']}\n\n"
        "Patient excerpts ({count} matched notes, chronological order):\n\n{excerpts}\n\n"
        "Based on ALL excerpts above, classify whether this patient has evidence of the event.\n"
        "Identify the EARLIEST confirmed occurrence date if positive. Respond with JSON only."
    )
    prompt = LLMPromptRevision(
        session_id=session.id,
        project_id=session.project_id,
        revision=revision + 1,
        **fields,
        llm_provider=project.llm_provider,
        llm_model=project.llm_model,
        llm_api_base=project.llm_api_base,
        template=template,
        generation_settings={"system_prompt": SYSTEM_PROMPT, "timeout": 120, "num_retries": 3},
        created_by=actor,
    )
    for key, value in fields.items():
        setattr(session, key, value)
    db.add(session)
    db.add(prompt)
    await flush(db)
    return prompt


def query_dict(query: SearchQuery) -> dict:
    return {
        key: getattr(query, key)
        for key in (
            "id",
            "query",
            "source_queries",
            "exclude_negated",
            "revision",
            "syntax_version",
        )
    }


def prompt_dict(prompt: LLMPromptRevision) -> dict:
    return {
        key: getattr(prompt, key)
        for key in (
            "id",
            "event_name",
            "event_description",
            "include_criteria",
            "exclude_criteria",
            "llm_provider",
            "llm_model",
            "revision",
        )
    }


async def attempt_dict(db: AsyncSession, attempt: EvaluationAttempt) -> dict:
    query = await db.get(SearchQuery, attempt.query_id)
    prompt = (
        await db.get(LLMPromptRevision, attempt.prompt_revision_id)
        if attempt.prompt_revision_id
        else None
    )
    run_id = await db.scalar(
        select(col(PipelineRun.id)).where(col(PipelineRun.attempt_id) == attempt.id)
    )
    assert query is not None
    return {
        "id": attempt.id,
        "sequence": attempt.sequence,
        "query_id": attempt.query_id,
        "prompt_revision_id": attempt.prompt_revision_id,
        "mode": attempt.mode,
        "scope": attempt.scope,
        "status": attempt.status,
        "metrics": attempt.metrics,
        "created_at": attempt.created_at,
        "progress": attempt.progress,
        "error_message": attempt.error_message,
        "source_attempt_id": attempt.source_attempt_id,
        "query_revision": query_dict(query),
        "prompt_revision": prompt_dict(prompt) if prompt else None,
        "pipeline_run_id": run_id,
    }


async def state(db: AsyncSession, session: EvaluationSession) -> dict:
    query = (
        await db.execute(
            select(SearchQuery)
            .where(
                col(SearchQuery.evaluation_session_id) == session.id,
            )
            .order_by(col(SearchQuery.revision).desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    prompt = (
        await db.execute(
            select(LLMPromptRevision)
            .where(
                col(LLMPromptRevision.session_id) == session.id,
            )
            .order_by(col(LLMPromptRevision.revision).desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    attempts = (
        (
            await db.execute(
                select(EvaluationAttempt)
                .where(
                    col(EvaluationAttempt.session_id) == session.id,
                )
                .order_by(col(EvaluationAttempt.sequence))
            )
        )
        .scalars()
        .all()
    )
    return {
        "query_revision": query_dict(query) if query else None,
        "prompt_revision": prompt_dict(prompt) if prompt else None,
        "attempts": [await attempt_dict(db, attempt) for attempt in attempts],
    }


async def runtime_config(db: AsyncSession, prompt: LLMPromptRevision) -> SimpleNamespace:
    project = await db.get(Project, prompt.project_id)
    if (
        not project
        or project.llm_provider != prompt.llm_provider
        or project.llm_api_base != prompt.llm_api_base
    ):
        raise HTTPException(
            409, "Project credentials no longer match this prompt provider and endpoint"
        )
    return SimpleNamespace(
        name=prompt.event_name,
        description=prompt.event_description,
        include_criteria=prompt.include_criteria,
        exclude_criteria=prompt.exclude_criteria,
        llm_provider=prompt.llm_provider,
        llm_model=prompt.llm_model,
        llm_api_base=prompt.llm_api_base,
        llm_api_key=project.llm_api_key,
        prompt_template=prompt.template,
        generation_settings=prompt.generation_settings,
    )


async def create_attempt(
    db: AsyncSession,
    session: EvaluationSession,
    query_id: str,
    actor: str,
    *,
    prompt_id: str | None = None,
    scope: str = "sample",
    source_id: str | None = None,
) -> EvaluationAttempt:
    query = await owned_query(db, session, query_id)
    prompt = await owned_prompt(db, session, prompt_id) if prompt_id else None
    if prompt:
        await runtime_config(db, prompt)
    sequence = (
        await db.scalar(
            select(func.max(col(EvaluationAttempt.sequence))).where(
                col(EvaluationAttempt.session_id) == session.id
            )
        )
    ) or 0
    patients = list(
        (
            await db.execute(
                select(col(Patient.id))
                .where(
                    col(Patient.project_id) == session.project_id,
                    col(Patient.deleted_at).is_(None),
                    *([col(Patient.id).in_(session.sample_patient_ids)] if scope == "sample" else []),
                )
                .order_by(col(Patient.id))
            )
        )
        .scalars()
        .all()
    )
    attempt = EvaluationAttempt(
        session_id=session.id,
        query_id=query.id,
        prompt_revision_id=prompt_id,
        sequence=sequence + 1,
        mode="llm" if prompt else "search",
        scope=scope,
        sample_patient_ids=patients,
        source_attempt_id=source_id,
        created_by=actor,
    )
    db.add(attempt)
    await flush(db)
    run = None
    if scope == "full":
        await db.execute(
            select(Project).where(col(Project.id) == session.project_id).with_for_update()
        )
        await db.execute(
            update(SearchQuery)
            .where(
                col(SearchQuery.project_id) == session.project_id,
                col(SearchQuery.is_active).is_(True),
                col(SearchQuery.deleted_at).is_(None),
            )
            .values(is_active=False)
        )
        query.is_active = True
        config = EventConfig(
            project_id=session.project_id,
            name=prompt.event_name if prompt else "Keyword search",
            description=prompt.event_description if prompt else "",
            include_criteria=prompt.include_criteria if prompt else "",
            exclude_criteria=prompt.exclude_criteria if prompt else "",
            llm_provider=prompt.llm_provider if prompt else "",
            llm_model=prompt.llm_model if prompt else "",
            llm_api_base=prompt.llm_api_base if prompt else None,
            search_patterns={"source_queries": query.source_queries},
            is_committed=True,
        )
        db.add(query)
        db.add(config)
        await flush(db)
        run = PipelineRun(
            project_id=session.project_id,
            event_config_id=config.id,
            attempt_id=attempt.id,
            evaluation_session_id=session.id,
            run_type="full",
            total_patients=len(patients),
            created_by=actor,
            snapshot_version=2,
            config_snapshot={
                "workflow_version": 2,
                "attempt_id": attempt.id,
                "query_id": query.id,
                "prompt_revision_id": prompt_id,
                "mode": attempt.mode,
            },
        )
        db.add(run)
        session.status = SessionStatus.COMMITTED
        session.committed_at = now_utc()
        session.committed_by = actor
        session.committed_config = run.config_snapshot
        db.add(
            AuditEntry(
                project_id=session.project_id,
                user_id=actor,
                action=AuditAction.PREDICTION_RAN,
                detail=run.config_snapshot,
            )
        )
    else:
        session.status = SessionStatus.REVIEWING
    db.add(session)
    for patient_id in patients:
        db.add(
            PatientResult(
                session_id=session.id,
                attempt_id=attempt.id,
                patient_id=patient_id,
                pipeline_run_id=run.id if run else None,
            )
        )
    await flush(db)
    return attempt


async def commit_attempt(
    db: AsyncSession, session: EvaluationSession, attempt_id: str, actor: str
) -> EvaluationAttempt:
    source = await owned_attempt(db, session, attempt_id)
    if source.scope != "sample" or source.mode != "llm" or source.status != "completed":
        raise HTTPException(409, "Select a successful sample LLM attempt")
    completed = await db.scalar(
        select(func.count())
        .select_from(PatientResult)
        .where(
            col(PatientResult.attempt_id) == source.id,
            col(PatientResult.status) == PatientResultStatus.COMPLETED,
        )
    )
    if not completed:
        raise HTTPException(409, "This attempt has no successful LLM classifications")
    return await create_attempt(
        db,
        session,
        source.query_id,
        actor,
        prompt_id=source.prompt_revision_id,
        scope="full",
        source_id=source.id,
    )


async def results(db: AsyncSession, attempt: EvaluationAttempt) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(PatientResult)
                .where(
                    col(PatientResult.attempt_id) == attempt.id,
                )
                .order_by(col(PatientResult.id))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            **row.model_dump(exclude={"input_snapshot"}, warnings=False),
            "finding_confidence": (
                row.predicted_score if row.finding_label == "positive" else 1 - row.predicted_score
            )
            if row.predicted_score is not None
            else None,
        }
        for row in rows
    ]


async def matched_notes(
    db: AsyncSession,
    session: EvaluationSession,
    attempt: EvaluationAttempt,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    from app.nlp.query_expression import select_note_sentences

    scope = (
        col(SearchMatch.session_id) == session.id,
        col(SearchMatch.attempt_id) == attempt.id,
    )
    note_ids = select(col(SearchMatch.note_id)).where(*scope).distinct().subquery()
    total = await db.scalar(select(func.count()).select_from(note_ids)) or 0
    selected_ids = list(
        (
            await db.execute(
                select(note_ids.c.note_id)
                .order_by(note_ids.c.note_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    matches = list(
        (
            await db.execute(
                select(SearchMatch)
                .where(*scope, col(SearchMatch.note_id).in_(selected_ids))
                .order_by(col(SearchMatch.id))
            )
        ).scalars()
    )
    patient_ids = {match.patient_id for match in matches}
    snapshots = {}
    for row in (
        await db.execute(
            select(PatientResult).where(
                col(PatientResult.session_id) == session.id,
                col(PatientResult.attempt_id) == attempt.id,
                col(PatientResult.patient_id).in_(patient_ids),
            )
        )
    ).scalars():
        for item in row.input_snapshot or []:
            if item["id"] in selected_ids:
                snapshots[(row.patient_id, item["id"])] = item
    notes = {
        note.id: note
        for note in (
            await db.execute(
                select(Note).where(
                    col(Note.project_id) == session.project_id, col(Note.id).in_(selected_ids)
                )
            )
        ).scalars()
    }
    query = None
    items = []
    for note_id in selected_ids:
        note_matches = [match for match in matches if match.note_id == note_id]
        patient_id = note_matches[0].patient_id
        snapshot = snapshots.get((patient_id, note_id))
        if snapshot is not None:
            text = snapshot["text"]
            note_date = snapshot["note_date"]
            sentences = snapshot["sentences"]
        else:
            note = notes.get(note_id)
            text = note.text if note else ""
            note_date = note.note_date if note else None
            if query is None:
                query = await owned_query(db, session, attempt.query_id)
            sentences = (
                select_note_sentences(
                    text, helper_rows(query.source_queries), exclude_negated=query.exclude_negated
                )
                if text
                else []
            )
        positions = {}
        for match in note_matches:
            for position in match.match_positions:
                key = (
                    position["token"],
                    position["note_start_index"],
                    position["note_end_index"],
                )
                positions[key] = {
                    "token": key[0],
                    "note_start_index": key[1],
                    "note_end_index": key[2],
                }
        items.append(
            {
                "note_id": note_id,
                "patient_id": patient_id,
                "text": text,
                "note_date": note_date,
                "matches": sorted(
                    positions.values(),
                    key=lambda position: (
                        position["note_start_index"],
                        position["note_end_index"],
                        position["token"],
                    ),
                ),
                "sentences": sentences,
            }
        )
    return {
        "notes": items,
        "total_notes": total,
        "page": page,
        "total_pages": (total + page_size - 1) // page_size,
    }


async def judge(
    db: AsyncSession,
    attempt: EvaluationAttempt,
    result_id: int,
    judgment: str,
    date_override: str | None,
    actor: str,
) -> PatientResult:
    if judgment not in ("correct", "wrong", "skipped"):
        raise HTTPException(422, "Judgment must be correct, wrong, or skipped")
    row = await db.get(PatientResult, result_id)
    if row is None or row.attempt_id != attempt.id or row.session_id != attempt.session_id:
        raise HTTPException(404, "Result not found in this attempt")
    if row.status != PatientResultStatus.COMPLETED:
        raise HTTPException(409, "Only completed results can be judged")
    row.review_judgment = judgment
    row.reviewer_date_override = date_override
    row.reviewed_by = actor
    row.reviewed_at = now_utc()
    db.add(row)
    await db.flush()
    await update_metrics(db, attempt)
    return row


async def update_metrics(db: AsyncSession, attempt: EvaluationAttempt) -> None:
    rows = (
        (
            await db.execute(
                select(PatientResult).where(
                    col(PatientResult.attempt_id) == attempt.id,
                )
            )
        )
        .scalars()
        .all()
    )
    counts = {
        status.value: sum(row.status == status for row in rows) for status in PatientResultStatus
    }
    reviewed = [row for row in rows if row.review_judgment in ("correct", "wrong")]
    tp = sum(
        row.finding_label == "positive" and row.review_judgment == "correct" for row in reviewed
    )
    fp = sum(row.finding_label == "positive" and row.review_judgment == "wrong" for row in reviewed)
    tn = sum(
        row.finding_label == "negative" and row.review_judgment == "correct" for row in reviewed
    )
    fn = sum(row.finding_label == "negative" and row.review_judgment == "wrong" for row in reviewed)
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    attempt.metrics = {
        **attempt.metrics,
        **counts,
        "total_patients": len(rows),
        "matched_patients": sum(row.notes_matched > 0 for row in rows),
        "matched_notes": sum(row.notes_matched for row in rows),
        "sample_notes": sum(row.notes_searched for row in rows),
        "sample_patients": len(rows),
        "total_reviewed": len(reviewed),
        "total_pending": sum(
            row.status == PatientResultStatus.COMPLETED and not row.review_judgment for row in rows
        ),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": (tp + tn) / len(reviewed) if reviewed else 0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
    }
    db.add(attempt)


async def execute_attempt(db: AsyncSession, attempt_id: str) -> None:
    from app.nlp.query_expression import select_note_sentences

    attempt = await db.get(EvaluationAttempt, attempt_id)
    if not attempt or attempt.status in ("completed", "cancelled"):
        return
    token = str(uuid4())
    stale = now_utc() - timedelta(minutes=15)
    claimed = await db.execute(
        update(EvaluationAttempt)
        .where(
            col(EvaluationAttempt.id) == attempt_id,
            (col(EvaluationAttempt.status).in_(["queued", "failed"]))
            | ((col(EvaluationAttempt.status) == "running") & (col(EvaluationAttempt.updated_at) < stale)),
        )
        .values(status="running", claim_token=token, updated_at=now_utc(), error_message=None)
    )
    await db.commit()
    if not cast(CursorResult[Any], claimed).rowcount:
        return
    await db.refresh(attempt)
    run = None
    try:
        run = (
            await db.execute(select(PipelineRun).where(col(PipelineRun.attempt_id) == attempt.id))
        ).scalar_one_or_none()
        session = await db.get(EvaluationSession, attempt.session_id)
        assert session is not None
        query = await owned_query(db, session, attempt.query_id)
        prompt = (
            await owned_prompt(db, session, attempt.prompt_revision_id)
            if attempt.prompt_revision_id
            else None
        )
        config = await runtime_config(db, prompt) if prompt else None
        lease = await db.execute(
            update(EvaluationAttempt)
            .where(
                col(EvaluationAttempt.id) == attempt.id,
                col(EvaluationAttempt.claim_token) == token,
                col(EvaluationAttempt.status) == "running",
            )
            .values(updated_at=now_utc())
        )
        if not cast(CursorResult[Any], lease).rowcount:
            await db.rollback()
            return
        if run:
            run.status = PipelineRunStatus.RUNNING
            run.started_at = run.started_at or now_utc()
            db.add(run)
        await db.commit()
        result_ids = list(
            (
                await db.execute(
                    select(col(PatientResult.id))
                    .where(
                        col(PatientResult.attempt_id) == attempt.id,
                    )
                    .order_by(col(PatientResult.id))
                )
            )
            .scalars()
            .all()
        )
        for result_id in result_ids:
            await db.refresh(attempt)
            if attempt.claim_token != token or attempt.status == "cancelled":
                return
            if run:
                await db.refresh(run)
                if run.is_cancelled:
                    attempt.status = "cancelled"
                    run.status = PipelineRunStatus.CANCELLED
                    db.add(attempt)
                    db.add(run)
                    await db.commit()
                    return
            row = await db.get(PatientResult, result_id)
            assert row is not None
            if row.status in (PatientResultStatus.COMPLETED, PatientResultStatus.NO_MATCH):
                continue
            patient = await db.get(Patient, row.patient_id)
            notes = (
                list(
                    (
                        await db.execute(
                            select(Note)
                            .where(
                                col(Note.project_id) == session.project_id,
                                col(Note.patient_id) == row.patient_id,
                                col(Note.deleted_at).is_(None),
                            )
                            .order_by(col(Note.note_date), col(Note.id))
                        )
                    )
                    .scalars()
                    .all()
                )
                if patient and patient.deleted_at is None
                else []
            )
            if row.input_snapshot is None:
                selected_notes = [
                    (
                        note,
                        select_note_sentences(
                            note.text,
                            helper_rows(query.source_queries),
                            exclude_negated=query.exclude_negated,
                        ),
                    )
                    for note in notes
                ]
                selected_notes = [(note, sentences) for note, sentences in selected_notes if sentences]
                row.input_snapshot = [
                    {
                        "id": note.id,
                        "text": note.text,
                        "note_date": note.note_date.isoformat(),
                        "sentences": sentences,
                    }
                    for note, sentences in selected_notes
                ]
                row.notes_searched = len(notes)
            selected = [
                (
                    SimpleNamespace(id=item["id"], text=item["text"], note_date=item["note_date"]),
                    item["sentences"],
                )
                for item in row.input_snapshot
            ]
            row.notes_matched = len(selected)
            row.pipeline_run_id = run.id if run else None
            row.started_at = now_utc()
            fingerprint = hashlib.sha256(
                json.dumps(
                    [(note.id, note.text) for note, _sentences in selected],
                    ensure_ascii=True,
                ).encode()
            ).hexdigest()
            attempt.metrics = {
                **attempt.metrics,
                "input_fingerprints": {
                    **attempt.metrics.get("input_fingerprints", {}),
                    row.patient_id: fingerprint,
                },
            }
            row.status = PatientResultStatus.PROCESSING
            db.add(row)
            db.add(attempt)
            with db.no_autoflush:
                lease = await db.execute(
                    update(EvaluationAttempt)
                    .where(
                        col(EvaluationAttempt.id) == attempt.id,
                        col(EvaluationAttempt.claim_token) == token,
                        col(EvaluationAttempt.status) == "running",
                    )
                    .values(updated_at=now_utc())
                )
            if not cast(CursorResult[Any], lease).rowcount:
                await db.rollback()
                return
            await db.commit()
            classification = None
            if not selected:
                row.status = PatientResultStatus.NO_MATCH
            elif config:
                try:
                    classification = await classify_patient(
                        [
                            {"note_id": note.id, "note_date": note.note_date, "text": note.text}
                            for note, _sentences in selected
                        ],
                        config,
                    )
                    row.finding_label = classification.label
                    row.predicted_score = classification.score
                    row.finding_reasoning = classification.reasoning
                    row.finding_evidence = classification.evidence
                    row.event_date = classification.event_date
                    row.token_usage = classification.token_usage
                    row.status = PatientResultStatus.COMPLETED
                    row.error_message = None
                except Exception:
                    row.status = PatientResultStatus.FAILED
                    row.error_message = "LLM classification failed; retry this attempt"
            else:
                row.status = PatientResultStatus.COMPLETED
            lease = await db.execute(
                update(EvaluationAttempt)
                .where(
                    col(EvaluationAttempt.id) == attempt.id,
                    col(EvaluationAttempt.claim_token) == token,
                    col(EvaluationAttempt.status) == "running",
                )
                .values(updated_at=now_utc())
            )
            if not cast(CursorResult[Any], lease).rowcount:
                await db.rollback()
                return
            prior = set(
                (
                    await db.execute(
                        select(col(SearchMatch.note_id)).where(
                            col(SearchMatch.attempt_id) == attempt.id,
                            col(SearchMatch.patient_id) == row.patient_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for note, sentences in selected:
                if note.id not in prior:
                    db.add(
                        SearchMatch(
                            session_id=session.id,
                            attempt_id=attempt.id,
                            query_id=query.id,
                            patient_id=row.patient_id,
                            note_id=note.id,
                            matched_tokens=list(
                                dict.fromkeys(
                                    token_text
                                    for sentence in sentences
                                    for token_text in sentence["matched_tokens"]
                                )
                            ),
                            match_positions=[
                                match for sentence in sentences for match in sentence["matches"]
                            ],
                            is_negated=any(sentence["is_negated"] for sentence in sentences),
                        )
                    )
                if run and row.status == PatientResultStatus.COMPLETED:
                    existing = set(
                        (
                            await db.execute(
                                select(col(Annotation.sentence_start), col(Annotation.sentence_end)).where(
                                    col(Annotation.attempt_id) == attempt.id,
                                    col(Annotation.note_id) == note.id,
                                )
                            )
                        ).all()
                    )
                    for sentence in sentences:
                        if (sentence["start_pos"], sentence["end_pos"]) in existing:
                            continue
                        db.add(
                            Annotation(
                                project_id=session.project_id,
                                patient_id=row.patient_id,
                                note_id=note.id,
                                pipeline_run_id=run.id,
                                attempt_id=attempt.id,
                                evaluation_session_id=session.id,
                                sentence_text=sentence["text"],
                                sentence_start=sentence["start_pos"],
                                sentence_end=sentence["end_pos"],
                                note_start_index=sentence["start_pos"],
                                note_end_index=sentence["end_pos"],
                                sentence_number=sentence["sentence_number"],
                                is_negated=sentence["is_negated"],
                                matched_tokens=",".join(sentence["matched_tokens"]),
                                predicted_score=classification.score if classification else None,
                                predicted_label=int(classification.label == "positive")
                                if classification
                                else None,
                                predictor_model=prompt.llm_model if prompt else "",
                                reasoning=classification.reasoning if classification else "",
                            )
                        )
            row.completed_at = now_utc()
            db.add(row)
            await db.flush()
            await update_metrics(db, attempt)
            done = (
                attempt.metrics["completed"]
                + attempt.metrics["no_match"]
                + attempt.metrics["failed"]
            )
            attempt.progress = int(100 * done / len(result_ids)) if result_ids else 100
            attempt.updated_at = now_utc()
            if run:
                run.progress = attempt.progress
                run.processed_patients = done
                run.failed_patients = attempt.metrics["failed"]
                run.updated_at = now_utc()
                db.add(run)
            db.add(attempt)
            await db.commit()
        terminal_lease = await db.execute(
            update(EvaluationAttempt)
            .where(
                col(EvaluationAttempt.id) == attempt.id,
                col(EvaluationAttempt.claim_token) == token,
                col(EvaluationAttempt.status) == "running",
            )
            .values(updated_at=now_utc())
        )
        if not cast(CursorResult[Any], terminal_lease).rowcount:
            await db.rollback()
            return
        await update_metrics(db, attempt)
        attempt.status = "failed" if attempt.metrics["failed"] else "completed"
        attempt.progress = 100
        attempt.updated_at = now_utc()
        if run:
            run.status = (
                PipelineRunStatus.FAILED
                if attempt.status == "failed"
                else PipelineRunStatus.COMPLETED
            )
            run.result_summary = attempt.metrics
            run.completed_at = now_utc()
            run.progress = 100
            db.add(run)
            if attempt.status == "completed":
                session.status = SessionStatus.COMPLETED
                db.add(session)
        db.add(attempt)
        await db.commit()
    except Exception:
        await db.rollback()
        owned = await db.execute(
            update(EvaluationAttempt)
            .where(
                col(EvaluationAttempt.id) == attempt_id,
                col(EvaluationAttempt.claim_token) == token,
                col(EvaluationAttempt.status) == "running",
            )
            .values(
                status="failed",
                error_message="Attempt execution failed; retry this attempt",
                updated_at=now_utc(),
            )
        )
        if run and cast(CursorResult[Any], owned).rowcount:
            run.status = PipelineRunStatus.FAILED
            db.add(run)
        await db.commit()


async def dispatch(db: AsyncSession, attempt: EvaluationAttempt) -> None:
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        try:
            if await redis.exists(b"arq:queue:health-check"):
                await redis.enqueue_job("run_query_first_attempt_job", attempt.id)
                return
        finally:
            await redis.aclose()
    except Exception:
        pass
    await execute_attempt(db, attempt.id)
