"""Evaluation service: sampling, prediction runs, judgment collection, metrics."""

import logging
import random
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import Note
from app.evaluation.models import (
    EvaluationJudgment,
    EvaluationSession,
    JudgmentValue,
    SessionStatus,
    ValidatedPredictor,
)
from app.nlp.models import Sentence
from app.predictors.base import PredictorError
from app.predictors.factory import create_predictor
from app.predictors.models import PredictorConfig

logger = logging.getLogger(__name__)


# ── Session management ───────────────────────────────────────────


async def create_session(
    session: AsyncSession,
    project_id: str,
    predictor_config_id: str,
    user_id: str,
    name: str = "",
    sample_config: dict | None = None,
) -> EvaluationSession:
    """Create an evaluation session and sample notes."""
    config = sample_config or {"size": 50, "keyword_match_ratio": 0.6, "keywords": []}

    eval_session = EvaluationSession(
        project_id=project_id,
        predictor_config_id=predictor_config_id,
        name=name,
        status=SessionStatus.SAMPLING,
        sample_config=config,
        created_by=user_id,
    )
    session.add(eval_session)
    await session.flush()

    # Sample notes using keyword-based stratification
    note_ids = await _sample_notes(session, project_id, config)
    eval_session.total_notes = len(note_ids)

    # Create judgment placeholders
    for note_id in note_ids:
        judgment = EvaluationJudgment(
            session_id=eval_session.id,
            note_id=note_id,
        )
        session.add(judgment)

    eval_session.status = SessionStatus.SAMPLING
    await session.commit()
    await session.refresh(eval_session)
    return eval_session


async def _sample_notes(
    session: AsyncSession,
    project_id: str,
    config: dict,
) -> list[str]:
    """Sample notes using keyword-based stratification.

    If keywords are provided, splits notes into matched/unmatched buckets
    and allocates according to keyword_match_ratio.
    """
    size = min(config.get("size", 50), 500)
    keywords = config.get("keywords", [])
    ratio = config.get("keyword_match_ratio", 0.6)

    if not keywords:
        # Random sample from all project notes
        stmt = select(Note.id).where(Note.project_id == project_id)
        result = await session.execute(stmt)
        all_ids = [r[0] for r in result.all()]
        random.shuffle(all_ids)
        return all_ids[:size]

    # Find notes with keyword-matching target sentences
    matched_stmt = (
        select(Sentence.note_id)
        .where(
            Sentence.project_id == project_id,
            Sentence.is_target == True,  # noqa: E712
        )
        .distinct()
    )
    result = await session.execute(matched_stmt)
    matched_ids = list({r[0] for r in result.all()})

    # All notes
    all_stmt = select(Note.id).where(Note.project_id == project_id)
    result = await session.execute(all_stmt)
    all_ids = [r[0] for r in result.all()]

    unmatched_ids = [nid for nid in all_ids if nid not in set(matched_ids)]

    random.shuffle(matched_ids)
    random.shuffle(unmatched_ids)

    # Allocate by ratio
    n_matched = min(int(size * ratio), len(matched_ids))
    n_unmatched = min(size - n_matched, len(unmatched_ids))

    # Backfill if either bucket is short
    selected = matched_ids[:n_matched] + unmatched_ids[:n_unmatched]
    remaining = size - len(selected)
    if remaining > 0:
        extras = [nid for nid in matched_ids[n_matched:] + unmatched_ids[n_unmatched:]
                  if nid not in set(selected)]
        selected.extend(extras[:remaining])

    return selected


async def run_predictions(
    session: AsyncSession,
    eval_session_id: str,
) -> EvaluationSession:
    """Run predictor on all sampled notes in the session."""
    eval_session = (
        await session.execute(
            select(EvaluationSession).where(EvaluationSession.id == eval_session_id)
        )
    ).scalar_one()

    # Get predictor
    predictor_config = (
        await session.execute(
            select(PredictorConfig).where(
                PredictorConfig.id == eval_session.predictor_config_id
            )
        )
    ).scalar_one()

    predictor = create_predictor(predictor_config)
    eval_session.status = SessionStatus.RUNNING
    session.add(eval_session)
    await session.commit()

    # Get all judgments for this session
    judgments = (
        await session.execute(
            select(EvaluationJudgment).where(
                EvaluationJudgment.session_id == eval_session_id
            )
        )
    ).scalars().all()

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0

    for judgment in judgments:
        if judgment.predicted_label is not None:
            continue  # Already predicted

        note = (
            await session.execute(select(Note).where(Note.id == judgment.note_id))
        ).scalar_one_or_none()

        if not note:
            continue

        try:
            result = await predictor.predict(note.text)
            judgment.predicted_label = result.label
            judgment.predicted_score = result.score
            judgment.reasoning = result.reasoning
            if result.token_usage:
                total_prompt_tokens += result.token_usage.prompt_tokens
                total_completion_tokens += result.token_usage.completion_tokens
                total_tokens += result.token_usage.total_tokens
        except PredictorError as e:
            logger.warning("Prediction failed for note %s: %s", judgment.note_id, e)
            judgment.predicted_label = None
            judgment.predicted_score = None
            judgment.reasoning = f"Error: {e}"

        session.add(judgment)

    eval_session.metrics = {
        **eval_session.metrics,
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    eval_session.status = SessionStatus.REVIEWING
    session.add(eval_session)
    await session.commit()
    await session.refresh(eval_session)
    return eval_session


# ── Judgment operations ──────────────────────────────────────────


async def get_next_pending(
    session: AsyncSession,
    eval_session_id: str,
) -> EvaluationJudgment | None:
    """Get the next pending judgment for review."""
    stmt = (
        select(EvaluationJudgment)
        .where(
            EvaluationJudgment.session_id == eval_session_id,
            EvaluationJudgment.judgment == JudgmentValue.PENDING,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_next_pending_with_note(
    session: AsyncSession,
    eval_session_id: str,
) -> dict | None:
    """Get the next pending judgment joined with its note text."""
    judgment = await get_next_pending(session, eval_session_id)
    if not judgment:
        return None

    note = (
        await session.execute(select(Note).where(Note.id == judgment.note_id))
    ).scalar_one_or_none()

    return {
        "id": judgment.id,
        "session_id": judgment.session_id,
        "note_id": judgment.note_id,
        "predicted_label": judgment.predicted_label,
        "predicted_score": judgment.predicted_score,
        "reasoning": judgment.reasoning,
        "judgment": judgment.judgment,
        "judged_by": judgment.judged_by,
        "judged_at": judgment.judged_at,
        "note_text": note.text if note else "",
        "note_text_id": note.text_id if note else "",
        "patient_id": note.patient_id if note else "",
    }


async def submit_judgment(
    session: AsyncSession,
    judgment_id: str,
    judgment_value: str,
    user_id: str,
) -> EvaluationJudgment | None:
    """Record a clinician's judgment and recompute metrics."""
    judgment = (
        await session.execute(
            select(EvaluationJudgment).where(EvaluationJudgment.id == judgment_id)
        )
    ).scalar_one_or_none()

    if not judgment:
        return None

    judgment.judgment = JudgmentValue(judgment_value)
    judgment.judged_by = user_id
    judgment.judged_at = datetime.now(UTC)
    session.add(judgment)

    # Recompute metrics for the session
    eval_session = (
        await session.execute(
            select(EvaluationSession).where(
                EvaluationSession.id == judgment.session_id
            )
        )
    ).scalar_one()

    metrics = await compute_metrics(session, judgment.session_id)
    eval_session.metrics = metrics
    eval_session.judged_notes = metrics["total_judged"]

    # Auto-complete session if all judged
    if metrics["total_pending"] == 0:
        eval_session.status = SessionStatus.COMPLETED
        eval_session.completed_at = datetime.now(UTC)

    session.add(eval_session)
    await session.commit()
    await session.refresh(judgment)
    return judgment


async def list_judgments(
    session: AsyncSession,
    eval_session_id: str,
) -> list[EvaluationJudgment]:
    stmt = (
        select(EvaluationJudgment)
        .where(EvaluationJudgment.session_id == eval_session_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── Metrics computation ──────────────────────────────────────────


async def compute_metrics(
    session: AsyncSession,
    eval_session_id: str,
) -> dict:
    """Compute P/R/F1/accuracy from judgments."""
    judgments = (
        await session.execute(
            select(EvaluationJudgment).where(
                EvaluationJudgment.session_id == eval_session_id
            )
        )
    ).scalars().all()

    tp = fp = tn = fn = 0
    total_judged = 0
    total_pending = 0

    for j in judgments:
        if j.judgment == JudgmentValue.PENDING:
            total_pending += 1
            continue
        if j.judgment == JudgmentValue.SKIPPED:
            continue

        total_judged += 1
        predicted_positive = j.predicted_label == 1

        if j.judgment == JudgmentValue.CORRECT:
            if predicted_positive:
                tp += 1
            else:
                tn += 1
        elif j.judgment == JudgmentValue.WRONG:
            if predicted_positive:
                fp += 1
            else:
                fn += 1

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "total_judged": total_judged,
        "total_pending": total_pending,
    }


# ── Validation ───────────────────────────────────────────────────


async def validate_predictor(
    session: AsyncSession,
    project_id: str,
    eval_session_id: str,
    user_id: str,
    name: str,
    notes: str = "",
    threshold: float = 0.5,
) -> ValidatedPredictor:
    """Validate the predictor config from an evaluation session."""
    eval_session = (
        await session.execute(
            select(EvaluationSession).where(EvaluationSession.id == eval_session_id)
        )
    ).scalar_one()

    predictor_config = (
        await session.execute(
            select(PredictorConfig).where(
                PredictorConfig.id == eval_session.predictor_config_id
            )
        )
    ).scalar_one()

    metrics = await compute_metrics(session, eval_session_id)

    # Carry forward token usage from session metrics
    if eval_session.metrics and "token_usage" in eval_session.metrics:
        metrics["token_usage"] = eval_session.metrics["token_usage"]

    validated = ValidatedPredictor(
        project_id=project_id,
        predictor_config_id=predictor_config.id,
        session_id=eval_session_id,
        name=name,
        notes=notes,
        config_snapshot=predictor_config.config,
        metrics_snapshot=metrics,
        threshold=threshold,
        validated_by=user_id,
    )
    session.add(validated)
    await session.commit()
    await session.refresh(validated)
    return validated


async def activate_validated_predictor(
    session: AsyncSession,
    project_id: str,
    validated_id: str,
) -> ValidatedPredictor | None:
    """Activate a validated predictor and its PredictorConfig.

    Does NOT trigger bulk predictions — that is the caller's responsibility.
    """
    # Deactivate current validated predictors
    stmt = select(ValidatedPredictor).where(
        ValidatedPredictor.project_id == project_id,
        ValidatedPredictor.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    for vp in result.scalars().all():
        vp.is_active = False
        session.add(vp)

    # Activate the new validated predictor
    validated = (
        await session.execute(
            select(ValidatedPredictor).where(ValidatedPredictor.id == validated_id)
        )
    ).scalar_one_or_none()

    if not validated:
        return None

    validated.is_active = True
    session.add(validated)

    # Also activate the corresponding PredictorConfig (and deactivate others)
    deactivate_stmt = select(PredictorConfig).where(
        PredictorConfig.project_id == project_id,
        PredictorConfig.is_active == True,  # noqa: E712
    )
    result = await session.execute(deactivate_stmt)
    for pc in result.scalars().all():
        pc.is_active = False
        session.add(pc)

    predictor_config = (
        await session.execute(
            select(PredictorConfig).where(
                PredictorConfig.id == validated.predictor_config_id
            )
        )
    ).scalar_one_or_none()

    if predictor_config:
        predictor_config.is_active = True
        session.add(predictor_config)

    await session.commit()
    await session.refresh(validated)
    return validated


# ── List helpers ─────────────────────────────────────────────────


async def list_sessions(
    session: AsyncSession,
    project_id: str,
) -> list[EvaluationSession]:
    stmt = (
        select(EvaluationSession)
        .where(EvaluationSession.project_id == project_id)
        .order_by(EvaluationSession.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_session(
    db: AsyncSession,
    session_id: str,
) -> EvaluationSession | None:
    result = await db.execute(
        select(EvaluationSession).where(EvaluationSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def list_validated_predictors(
    session: AsyncSession,
    project_id: str,
) -> list[ValidatedPredictor]:
    stmt = (
        select(ValidatedPredictor)
        .where(ValidatedPredictor.project_id == project_id)
        .order_by(ValidatedPredictor.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
