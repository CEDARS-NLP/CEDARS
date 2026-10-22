"""Coordinator for durable, generation-fenced production note processing."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationPrediction
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.engine import parse_query, process_note
from app.production.classifier import NoteClassification, classify_note
from app.production.models import NotePrediction, ProductionResult, ProductionRun, ProductionState
from app.projects.models import Project

logger = logging.getLogger(__name__)


class ProductionError(ValueError):
    """Base exception for rejected production run operations."""


class ProductionConfirmationRequired(ProductionError):
    """Raised when a destructive replacement needs explicit confirmation."""


class ProductionLockedError(ProductionError):
    """Raised when a patient is currently held by a reviewer."""


class ObsoleteRun(ProductionError):
    """Raised when a worker's run no longer owns the project generation."""


def _value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        candidate = getattr(source, name, None)
        if candidate is not None:
            return candidate
    return default


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "dict") and callable(value.dict):
        value = value.dict()
    if isinstance(value, dict):
        return {
            str(key): _plain(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in ("api_key", "secret", "password"))
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _snapshot(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        return _plain(config)
    if hasattr(config, "model_dump"):
        return _plain(config.model_dump(mode="json"))
    if hasattr(config, "dict"):
        return _plain(config.dict())
    return _plain(vars(config))


def _fingerprint(value: Any) -> str:
    serialized = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _query(config: dict[str, Any]) -> str:
    config = _value(config, "config", default=config)
    value = _value(config, "query", "search_query", "keyword_query", default="")
    if isinstance(value, dict):
        value = _value(value, "query", "expression", default="")
    return str(value or "")


def _llm_enabled(config: dict[str, Any]) -> bool:
    config = _value(config, "config", default=config)
    llm = _value(config, "llm_config", "llm", default={})
    provider = _value(llm, "provider", "llm_provider") or _value(config, "provider", "llm_provider")
    model = _value(llm, "model", "llm_model") or _value(config, "model", "llm_model")
    return bool(provider and model)


def _now() -> datetime:
    return datetime.now(UTC)


async def _has_existing_data(db: AsyncSession, project_id: str) -> bool:
    for model in (Annotation, AnnotationPrediction, NotePrediction, ProductionResult):
        row = await db.scalar(select(model).where(model.project_id == project_id).limit(1))
        if row is not None:
            return True
    patient = await db.scalar(
        select(Patient.id)
        .where(
            Patient.project_id == project_id,
            (Patient.event_date.is_not(None))
            | (Patient.reviewed_at.is_not(None))
            | (Patient.review_reason.is_not(None)),
        )
        .limit(1)
    )
    return patient is not None


async def _reset_project(db: AsyncSession, project_id: str) -> None:
    locked = list(
        await db.scalars(
            select(Patient.patient_id_ext).where(
                Patient.project_id == project_id,
                Patient.deleted_at.is_(None),
                (Patient.locked_by.is_not(None)) | (Patient.locked_at.is_not(None)),
            )
        )
    )
    if locked:
        raise ProductionLockedError(
            f"Cannot replace production data while {len(locked)} patient review(s) are locked"
        )

    await db.execute(
        update(Patient)
        .where(Patient.project_id == project_id)
        .values(
            event_date=None,
            event_annotation_id=None,
            event_reviewer=None,
            status=PatientStatus.NEW,
            review_source=None,
            review_reason=None,
            reviewed_by=None,
            reviewed_at=None,
            locked_by=None,
            locked_at=None,
        )
    )
    await db.execute(delete(ProductionResult).where(ProductionResult.project_id == project_id))
    await db.execute(
        update(Annotation)
        .where(Annotation.project_id == project_id)
        .values(duplicate_of=None, skipped_by_event_annotation_id=None)
    )
    annotation_ids = select(Annotation.annotation_id).where(Annotation.project_id == project_id)
    await db.execute(
        delete(AnnotationPrediction).where(AnnotationPrediction.annotation_id.in_(annotation_ids))
    )
    await db.execute(delete(NotePrediction).where(NotePrediction.project_id == project_id))
    await db.execute(delete(Annotation).where(Annotation.project_id == project_id))


async def start_run(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    config: Any,
    confirmed: bool = False,
) -> ProductionRun:
    """Reset project-derived production data and activate a new run generation."""
    snapshot = _snapshot(config)
    parse_query(_query(snapshot))
    async with db.begin_nested():
        state = await db.scalar(
            select(ProductionState)
            .where(ProductionState.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if state is None:
            state = ProductionState(project_id=project_id)
            db.add(state)
            await db.flush()

        has_data = await _has_existing_data(db, project_id)
        if has_data and not confirmed:
            raise ProductionConfirmationRequired(
                "Production data already exists; confirm replacement to reset annotations, "
                "predictions, results, and patient review/event fields"
            )
        await _reset_project(db, project_id)

        previous = await db.get(ProductionRun, state.active_run_id) if state.active_run_id else None
        if previous and previous.status in {"queued", "running"}:
            previous.status = "cancelled"
            previous.cancelled_at = _now()

        patients = list(
            await db.scalars(
                select(Patient).where(
                    Patient.project_id == project_id,
                    Patient.deleted_at.is_(None),
                )
            )
        )
        patient_by_id = {patient.id: patient for patient in patients}
        notes = list(
            await db.scalars(
                select(Note).where(Note.project_id == project_id, Note.deleted_at.is_(None))
            )
        )
        notes = [note for note in notes if note.patient_id in patient_by_id]
        run = ProductionRun(
            project_id=project_id,
            created_by=user_id,
            status="queued",
            config_snapshot=snapshot,
            config_fingerprint=_fingerprint(snapshot),
            total_notes=len(notes),
            progress_metadata={"keyword_matches": 0, "generation": state.generation + 1},
        )
        db.add(run)
        await db.flush()
        state.active_run_id = run.id
        state.generation += 1
        for patient in patients:
            db.add(
                ProductionResult(
                    project_id=project_id,
                    patient_uuid=patient.id,
                    patient_id=patient.patient_id_ext,
                    processing_status="queued",
                    review_status="pending",
                )
            )
    await db.commit()
    await db.refresh(run)
    return run


async def _active_run(db: AsyncSession, run_id: str) -> tuple[ProductionRun, ProductionState]:
    run = await db.scalar(
        select(ProductionRun)
        .where(ProductionRun.id == run_id)
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise ProductionError("Production run was not found")
    state = await db.scalar(
        select(ProductionState)
        .where(ProductionState.project_id == run.project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state is None or state.active_run_id != run_id:
        raise ObsoleteRun("Production run no longer owns the active project generation")
    return run, state


async def _fence(db: AsyncSession, run_id: str) -> ProductionRun:
    run, _ = await _active_run(db, run_id)
    if run.status == "cancelled":
        raise ObsoleteRun("Production run was cancelled")
    return run


async def _refresh_results(db: AsyncSession, project_id: str, patient_id: str):
    from app.production.results import refresh_patient_result

    return await refresh_patient_result(db, project_id, patient_id)


async def _patient_completion(db: AsyncSession, run: ProductionRun, patient: Patient) -> None:
    predictions = list(
        await db.scalars(
            select(NotePrediction).where(
                NotePrediction.run_id == run.id,
                NotePrediction.project_id == run.project_id,
                NotePrediction.patient_id == patient.patient_id_ext,
            )
        )
    )
    if any(prediction.status in {"queued", "processing", "failed"} for prediction in predictions):
        patient.status = PatientStatus.NLP_PROCESSING
        await _refresh_results(db, run.project_id, patient.id)
        return

    pending_count = await db.scalar(
        select(Annotation.annotation_id)
        .where(
            Annotation.project_id == run.project_id,
            Annotation.production_run_id == run.id,
            Annotation.patient_id == patient.patient_id_ext,
            Annotation.status == "U",
        )
        .limit(1)
    )
    patient.status = PatientStatus.REVIEWED if pending_count is None else PatientStatus.NLP_COMPLETE
    patient.review_source = "production"
    patient.review_reason = "production_complete"
    result = await db.scalar(
        select(ProductionResult).where(
            ProductionResult.project_id == run.project_id,
            ProductionResult.patient_uuid == patient.id,
        )
    )
    if result:
        result.processing_status = "completed"
        result.review_status = (
            "completed" if patient.status == PatientStatus.REVIEWED else "pending"
        )
        result.notes_total = len(predictions)
        result.notes_processed = sum(item.status == "succeeded" for item in predictions)
        result.notes_failed = sum(item.status == "failed" for item in predictions)
        result.failure_count = result.notes_failed
        result.last_error = next((item.error for item in predictions if item.error), None)
    refreshed = await _refresh_results(db, run.project_id, patient.id)
    if refreshed:
        refreshed.processing_status = "completed"
        refreshed.review_status = (
            "completed" if patient.status == PatientStatus.REVIEWED else "pending"
        )
        source_note_count = await db.scalar(
            select(func.count())
            .select_from(Note)
            .where(
                Note.project_id == run.project_id,
                Note.patient_id == patient.id,
                Note.deleted_at.is_(None),
            )
        )
        if not predictions:
            refreshed.notes_total = source_note_count or 0
            refreshed.notes_processed = source_note_count or 0


def _record_completed_note(run: ProductionRun, text_id: str) -> None:
    metadata = dict(run.progress_metadata or {})
    completed = set(metadata.get("completed_note_ids", []))
    completed.add(text_id)
    metadata["completed_note_ids"] = sorted(completed)
    run.progress_metadata = metadata
    run.completed_notes = min(run.total_notes, len(completed))


def _record_note_scan(run: ProductionRun, text_id: str, match_count: int) -> None:
    metadata = dict(run.progress_metadata or {})
    counts = dict(metadata.get("scanned_note_match_counts", {}))
    counts.setdefault(text_id, match_count)
    metadata["scanned_note_match_counts"] = counts
    metadata["keyword_matches"] = sum(counts.values())
    run.progress_metadata = metadata


def _match_key(sentence: str) -> str:
    return sentence.lower().strip()


async def _create_matches(
    db: AsyncSession,
    run: ProductionRun,
    note: Note,
    patient: Patient,
    config: dict[str, Any],
    query_groups: list[list[dict]],
) -> list[Annotation]:
    existing = list(
        await db.scalars(
            select(Annotation).where(
                Annotation.project_id == run.project_id,
                Annotation.production_run_id == run.id,
                Annotation.text_id == note.text_id,
            )
        )
    )
    if existing:
        return existing

    sentences = process_note(note.text, query_groups)
    all_existing = list(
        await db.scalars(
            select(Annotation).where(
                Annotation.project_id == run.project_id,
                Annotation.production_run_id == run.id,
                Annotation.patient_id == patient.patient_id_ext,
            )
        )
    )
    retained_by_sentence: dict[str, Annotation] = {}
    for annotation in all_existing:
        retained_by_sentence.setdefault(_match_key(annotation.sentence), annotation)

    exclude_negated = bool(_value(config, "exclude_negated", "exclude_negations", default=False))
    hide_duplicates = bool(_value(config, "hide_duplicates", default=False))
    note_date = note.note_date.date()
    created: list[Annotation] = []
    note_sentence_keys: set[str] = set()
    for sentence_info in sentences:
        if not sentence_info.get("is_target"):
            continue
        sentence = sentence_info["text"]
        key = _match_key(sentence)
        is_negated = bool(sentence_info.get("is_negated"))
        sentence_seen = key in note_sentence_keys
        duplicate = retained_by_sentence.get(key) if (hide_duplicates or sentence_seen) else None
        note_sentence_keys.add(key)
        first_match = None
        for match in sentence_info.get("matches", []):
            duplicate_for_match = duplicate or first_match
            annotation = Annotation(
                project_id=run.project_id,
                text_id=note.text_id,
                patient_id=patient.patient_id_ext,
                patient_uuid=patient.id,
                note_uuid=note.id,
                text_date=note_date,
                sentence=sentence,
                token=match["token"],
                isNegated=is_negated,
                note_start_index=int(match["note_start_index"]),
                note_end_index=int(match["note_end_index"]),
                sentence_number=int(sentence_info["sentence_number"]),
                sentence_start=int(sentence_info["start_pos"]),
                sentence_end=int(sentence_info["end_pos"]),
                status="R" if duplicate_for_match or (is_negated and exclude_negated) else "U",
                review_reason=(
                    "duplicate"
                    if duplicate_for_match
                    else "negated"
                    if is_negated and exclude_negated
                    else None
                ),
                actor_type="system"
                if duplicate_for_match or (is_negated and exclude_negated)
                else None,
                duplicate_of=duplicate_for_match.annotation_id if duplicate_for_match else None,
                production_run_id=run.id,
            )
            db.add(annotation)
            created.append(annotation)
            if duplicate_for_match is None and first_match is None:
                await db.flush()
                first_match = annotation
                retained_by_sentence.setdefault(key, annotation)
    if created:
        await db.flush()
    return created


async def _classify_and_store(
    db: AsyncSession,
    run_id: str,
    prediction: NotePrediction,
    note: Note,
    config: dict[str, Any],
    patient: Patient,
    api_key: str | None,
) -> bool:
    run = await _fence(db, run_id)
    prediction_id = prediction.id
    patient_uuid = patient.id
    note_text_id = note.text_id
    note_text = note.text
    claimed = await db.execute(
        update(NotePrediction)
        .where(
            NotePrediction.id == prediction_id,
            NotePrediction.run_id == run_id,
            NotePrediction.status == "queued",
        )
        .values(
            status="processing",
            attempts=NotePrediction.attempts + 1,
            started_at=_now(),
            claimed_at=_now(),
            error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await db.commit()
        return False
    await db.commit()

    try:
        classifier_config = {**config, "text_id": note_text_id}
        classification: NoteClassification = await classify_note(
            note_text, classifier_config, api_key=api_key
        )
    except Exception as exc:
        run = await _fence(db, run_id)
        prediction = await db.get(NotePrediction, prediction_id, populate_existing=True)
        patient = await db.get(Patient, patient_uuid, populate_existing=True)
        if prediction is None or patient is None:
            raise ObsoleteRun(
                "Prediction or patient row disappeared while classification was running"
            )
        prediction.status = "failed"
        prediction.error = str(exc)[:2000]
        prediction.completed_at = _now()
        run.failed_notes += 1
        run.error_summary = f"One or more note classifications failed ({run.failed_notes})"
        patient.status = PatientStatus.NLP_PROCESSING
        result = await db.scalar(
            select(ProductionResult).where(
                ProductionResult.project_id == run.project_id,
                ProductionResult.patient_uuid == patient.id,
            )
        )
        if result:
            result.processing_status = "failed"
            result.notes_failed += 1
            result.failure_count += 1
            result.last_error = prediction.error
        await _refresh_results(db, run.project_id, patient.id)
        await db.commit()
        return True

    run = await _fence(db, run_id)
    prediction = await db.get(NotePrediction, prediction_id, populate_existing=True)
    patient = await db.get(Patient, patient_uuid, populate_existing=True)
    if prediction is None or patient is None:
        raise ObsoleteRun("Prediction or patient row disappeared while classification was running")
    prediction.status = "succeeded"
    prediction.label = classification.label
    prediction.score = classification.score
    prediction.reasoning = classification.reasoning
    prediction.evidence_spans = classification.evidence_spans
    prediction.token_usage = classification.token_usage
    prediction.completed_at = _now()
    _record_completed_note(run, note_text_id)
    from app.llm.usage import add_usage

    llm = _value(config, "llm_config", "llm", default={})
    add_usage(
        db,
        project_id=run.project_id,
        source="production_run",
        ref_id=run.id,
        user_id=run.created_by,
        provider=_value(llm, "provider", "llm_provider")
        or _value(config, "provider", "llm_provider"),
        model=_value(llm, "model", "llm_model") or _value(config, "model", "llm_model"),
        usage=classification.token_usage,
    )
    annotations = list(
        await db.scalars(
            select(Annotation).where(
                Annotation.project_id == run.project_id,
                Annotation.production_run_id == run.id,
                Annotation.text_id == note_text_id,
                Annotation.status == "U",
            )
        )
    )
    if classification.label == 0:
        for annotation in annotations:
            annotation.status = "R"
            annotation.review_reason = "llm_negative"
            annotation.actor_type = "system"
            annotation.reviewed_at = _now()
    result = await db.scalar(
        select(ProductionResult).where(
            ProductionResult.project_id == run.project_id,
            ProductionResult.patient_uuid == patient.id,
        )
    )
    if result:
        result.processing_status = "running"
        result.notes_processed += 1
    await _patient_completion(db, run, patient)
    await db.commit()
    return True


async def execute_run(
    db: AsyncSession, run_id: str, *, _resume_claimed: bool = False
) -> ProductionRun:
    """Search project notes and classify each matched note independently."""
    run, _ = await _active_run(db, run_id)
    if _resume_claimed:
        if run.status != "running":
            raise ProductionError(f"Cannot resume a {run.status} production run")
    else:
        claim = await db.execute(
            update(ProductionRun)
            .where(ProductionRun.id == run_id, ProductionRun.status == "queued")
            .values(status="running", started_at=func.coalesce(ProductionRun.started_at, _now()))
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount != 1:
            await db.rollback()
            raise ProductionError("Production run is already claimed or is not queued")
        await db.refresh(run)
    if run.status != "running":
        raise ProductionError(f"Cannot execute a {run.status} production run")
    await db.commit()
    config = _value(run.config_snapshot or {}, "config", default=run.config_snapshot or {})
    query_groups = parse_query(_query(config))
    project = await db.scalar(
        select(Project)
        .where(Project.id == run.project_id)
        .execution_options(populate_existing=True)
    )
    api_key = project.llm_api_key if project else None
    patients = {
        patient.id: patient
        for patient in await db.scalars(
            select(Patient).where(
                Patient.project_id == run.project_id,
                Patient.deleted_at.is_(None),
            )
        )
    }
    notes = list(
        await db.scalars(
            select(Note)
            .where(Note.project_id == run.project_id, Note.deleted_at.is_(None))
            .order_by(Note.note_date, Note.text_id)
        )
    )
    llm_enabled = _llm_enabled(config)
    predictions_by_text: dict[str, NotePrediction] = {}

    # Search the complete source set first so patient readiness sees every
    # matched note before any one prediction can mark that patient complete.
    for note in notes:
        await _fence(db, run_id)
        patient = patients.get(note.patient_id)
        if patient is None:
            continue
        matches = await _create_matches(db, run, note, patient, config, query_groups)
        await db.flush()
        eligible_matches = [
            annotation
            for annotation in matches
            if annotation.status == "U" and annotation.review_reason is None
        ]
        _record_note_scan(run, note.text_id, len(matches))
        if not eligible_matches:
            _record_completed_note(run, note.text_id)
        elif not llm_enabled:
            _record_completed_note(run, note.text_id)
        else:
            patient.status = PatientStatus.NLP_PROCESSING
            result = await db.scalar(
                select(ProductionResult).where(
                    ProductionResult.project_id == run.project_id,
                    ProductionResult.patient_uuid == patient.id,
                )
            )
            if result:
                result.processing_status = "running"
            prediction = await db.scalar(
                select(NotePrediction).where(
                    NotePrediction.project_id == run.project_id,
                    NotePrediction.text_id == note.text_id,
                )
            )
            if prediction is None:
                llm = _value(config, "llm_config", "llm", default={})
                prediction = NotePrediction(
                    project_id=run.project_id,
                    run_id=run.id,
                    text_id=note.text_id,
                    patient_id=patient.patient_id_ext,
                    note_uuid=note.id,
                    patient_uuid=patient.id,
                    status="queued",
                    model_fingerprint=_fingerprint(
                        {
                            "provider": _value(llm, "provider", "llm_provider")
                            or _value(config, "provider", "llm_provider"),
                            "model": _value(llm, "model", "llm_model")
                            or _value(config, "model", "llm_model", default=""),
                        }
                    ),
                    config_fingerprint=run.config_fingerprint,
                )
                db.add(prediction)
                await db.flush()
            predictions_by_text[note.text_id] = prediction
        await db.commit()

    for patient in patients.values():
        await _patient_completion(db, run, patient)
    await db.commit()

    if llm_enabled:
        notes_by_text = {note.text_id: note for note in notes}
        for text_id, prediction in predictions_by_text.items():
            await _fence(db, run_id)
            if prediction.status == "succeeded":
                continue
            if prediction.status != "queued":
                continue
            note = notes_by_text[text_id]
            patient = patients[note.patient_id]
            await _classify_and_store(db, run.id, prediction, note, config, patient, api_key)

    run = await _fence(db, run_id)
    failures = run.failed_notes
    run.status = "failed" if failures else "completed"
    run.completed_at = _now()
    run.error_summary = run.error_summary if failures else None
    for patient in patients.values():
        await _patient_completion(db, run, patient)
    await db.commit()
    return run


async def resume_run(db: AsyncSession, run_id: str) -> ProductionRun:
    run, _ = await _active_run(db, run_id)
    if run.status == "completed":
        raise ProductionError("Completed production runs cannot be resumed")
    if run.status == "running":
        raise ProductionError("A running production run cannot be resumed concurrently")
    for prediction in await db.scalars(
        select(NotePrediction).where(
            NotePrediction.run_id == run_id, NotePrediction.status == "processing"
        )
    ):
        prediction.status = "queued"
    run.status = "running"
    run.cancelled_at = None
    await db.commit()
    return await execute_run(db, run_id, _resume_claimed=True)


async def retry_run(db: AsyncSession, run_id: str) -> ProductionRun:
    run, _ = await _active_run(db, run_id)
    failed = list(
        await db.scalars(
            select(NotePrediction).where(
                NotePrediction.run_id == run_id,
                NotePrediction.status == "failed",
            )
        )
    )
    if not failed:
        return await resume_run(db, run_id)
    for prediction in failed:
        prediction.status = "queued"
        prediction.error = None
        prediction.completed_at = None
    run.failed_notes = 0
    run.status = "queued"
    run.error_summary = None
    for result in await db.scalars(
        select(ProductionResult).where(
            ProductionResult.project_id == run.project_id,
            ProductionResult.processing_status == "failed",
        )
    ):
        result.processing_status = "queued"
        result.notes_failed = 0
        result.failure_count = 0
        result.last_error = None
    run.status = "running"
    await db.commit()
    return await execute_run(db, run_id, _resume_claimed=True)


async def cancel_run(db: AsyncSession, run_id: str) -> ProductionRun:
    run, _ = await _active_run(db, run_id)
    if run.status in {"completed", "failed", "cancelled"}:
        return run
    run.status = "cancelled"
    run.cancelled_at = _now()
    await db.commit()
    return run


async def get_stats(db: AsyncSession, run_id: str) -> dict[str, Any]:
    run, _ = await _active_run(db, run_id)
    predictions = list(
        await db.scalars(select(NotePrediction).where(NotePrediction.run_id == run_id))
    )
    annotations = list(
        await db.scalars(
            select(Annotation).where(
                Annotation.project_id == run.project_id,
                Annotation.production_run_id == run_id,
            )
        )
    )
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "total_notes": run.total_notes,
        "completed_notes": run.completed_notes,
        "failed_notes": run.failed_notes,
        "queued_notes": sum(item.status == "queued" for item in predictions),
        "processing_notes": sum(item.status == "processing" for item in predictions),
        "annotations_total": len(annotations),
        "annotations_pending": sum(item.status == "U" for item in annotations),
        "annotations_reviewed": sum(item.status == "R" for item in annotations),
        "progress_metadata": run.progress_metadata,
        "error_summary": run.error_summary,
    }


__all__ = [
    "ObsoleteRun",
    "ProductionConfirmationRequired",
    "ProductionError",
    "ProductionLockedError",
    "cancel_run",
    "execute_run",
    "get_stats",
    "resume_run",
    "retry_run",
    "start_run",
]
