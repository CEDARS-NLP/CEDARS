"""Business logic for data sources, ingestion, patients, and notes."""

import io
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction
from app.audit.service import log_action
from app.connectors.models import (
    ConnectorType,
    DataSource,
    IngestionStatus,
    Note,
    Patient,
)
from app.connectors.registry import get_connector

logger = logging.getLogger(__name__)


# ── Data Source CRUD ──────────────────────────────────────────────


async def create_data_source(
    session: AsyncSession,
    project_id: str,
    name: str,
    connector_type: ConnectorType,
    config: dict,
) -> DataSource:
    ds = DataSource(
        project_id=project_id,
        name=name,
        connector_type=connector_type,
        config=config,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


async def list_data_sources(
    session: AsyncSession, project_id: str
) -> list[DataSource]:
    stmt = (
        select(DataSource)
        .where(DataSource.project_id == project_id, DataSource.deleted_at.is_(None))
        .order_by(DataSource.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> DataSource | None:
    stmt = select(DataSource).where(
        DataSource.id == data_source_id,
        DataSource.project_id == project_id,
        DataSource.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> bool:
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        return False
    ds.deleted_at = datetime.now(UTC)
    session.add(ds)
    await session.commit()
    return True


# ── File Upload ──────────────────────────────────────────────────


async def upload_and_create_data_source(
    session: AsyncSession,
    project_id: str,
    filename: str,
    file_data: bytes,
    content_type: str,
    column_mapping: str | None = None,
) -> DataSource:
    """Validate upload, store in S3, create data source record.

    Raises ValueError for invalid inputs.
    """
    from app.common.s3 import upload_file
    from app.config import settings

    if not settings.s3_bucket or not settings.s3_endpoint:
        raise EnvironmentError(
            "Object storage is not configured. Set CEDARS_S3_ENDPOINT and CEDARS_S3_BUCKET."
        )

    if not filename:
        raise ValueError("Filename is required")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("csv", "json"):
        raise ValueError("Only CSV and JSON files are supported")

    # Parse column mapping
    mapping = {"patient_id": "patient_id", "text_id": "text_id", "text": "text", "note_date": "note_date"}
    if column_mapping:
        try:
            user_mapping = json.loads(column_mapping)
            if isinstance(user_mapping, dict):
                mapping.update(user_mapping)
        except json.JSONDecodeError:
            raise ValueError("column_mapping must be valid JSON")

    for required in ("patient_id", "text_id", "text", "note_date"):
        if not mapping.get(required):
            raise ValueError(f"Column mapping must include '{required}'")

    # Upload to S3
    s3_key = f"projects/{project_id}/uploads/{uuid.uuid4()}/{filename}"
    upload_file(s3_key, io.BytesIO(file_data), content_type=content_type)

    config = {
        "s3_key": s3_key,
        "file_type": ext,
        "column_mapping": mapping,
    }

    return await create_data_source(session, project_id, filename, ConnectorType.FILE_UPLOAD, config)


# ── Ingestion ─────────────────────────────────────────────────────


async def _run_ingestion_pipeline(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    row_handler,
    audit_action: AuditAction,
) -> DataSource:
    """Shared pipeline: validate connector, fetch batches, call row_handler, update status."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise ValueError("Data source not found")

    connector = get_connector(ds.connector_type)

    errors = await connector.validate_config(ds.config)
    if errors:
        ds.status = IngestionStatus.FAILED
        ds.error_message = "; ".join(errors)
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
        return ds

    ds.status = IngestionStatus.RUNNING
    ds.error_message = None
    session.add(ds)
    await session.commit()

    try:
        total_rows = 0
        offset = 0
        batch_size = 1000

        while True:
            batch = await connector.fetch(ds.config, batch_size=batch_size, offset=offset)
            if not batch.rows:
                break

            mapping = ds.config.get("column_mapping", {})
            count = await row_handler(session, project_id, ds.id, batch.rows, mapping)
            total_rows += count
            offset += batch_size

            if not batch.has_more:
                break

        ds.status = IngestionStatus.COMPLETED
        ds.row_count = total_rows
        ds.last_sync = datetime.now(UTC)
        ds.error_message = None

    except Exception as exc:
        ds.status = IngestionStatus.FAILED
        ds.error_message = str(exc)

    session.add(ds)
    await session.commit()
    await session.refresh(ds)

    if ds.status == IngestionStatus.COMPLETED:
        await log_action(
            session, project_id, audit_action,
            detail={"data_source_id": data_source_id, "row_count": total_rows},
        )

    return ds


async def run_ingestion(
    session: AsyncSession, project_id: str, data_source_id: str
) -> DataSource:
    """Fetch data from connector and insert patients + notes in batches."""
    return await _run_ingestion_pipeline(
        session, project_id, data_source_id, _ingest_rows, AuditAction.DATA_INGESTED,
    )


async def resync_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> DataSource:
    """Re-fetch data from connector. Update existing notes by text_id, insert new ones."""
    return await _run_ingestion_pipeline(
        session, project_id, data_source_id, _upsert_rows, AuditAction.DATA_RESYNCED,
    )


def _normalize_columns(
    rows: list[dict],
    column_mapping: dict,
) -> dict[str, str | None]:
    """Resolve logical column names to actual CSV column names using normalized matching.

    Returns a dict with keys: patient_id, text_id, text, note_date, source_ref.
    """
    resolved = {
        "patient_id": column_mapping.get("patient_id", "patient_id"),
        "text_id": column_mapping.get("text_id", "text_id"),
        "text": column_mapping.get("text", "text"),
        "note_date": column_mapping.get("note_date"),
        "source_ref": column_mapping.get("source_ref"),
    }

    if not rows:
        return resolved

    actual_keys = list(rows[0].keys())
    norm_lookup: dict[str, str] = {}
    for key in actual_keys:
        normalized = key.strip().lower().replace(" ", "_")
        norm_lookup[normalized] = key

    def resolve(mapped_name: str | None) -> str | None:
        if mapped_name is None:
            return None
        if mapped_name in rows[0]:
            return mapped_name
        normalized = mapped_name.strip().lower().replace(" ", "_")
        return norm_lookup.get(normalized, mapped_name)

    resolved["patient_id"] = resolve(resolved["patient_id"]) or resolved["patient_id"]
    resolved["text_id"] = resolve(resolved["text_id"]) or resolved["text_id"]
    resolved["text"] = resolve(resolved["text"]) or resolved["text"]
    resolved["note_date"] = resolve(resolved["note_date"])
    resolved["source_ref"] = resolve(resolved["source_ref"])

    return resolved


async def _upsert_rows(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    rows: list[dict],
    column_mapping: dict,
) -> int:
    """Insert new rows or update existing ones (matched by text_id)."""
    cols = _normalize_columns(rows, column_mapping)
    pid_col = cols["patient_id"]
    text_id_col = cols["text_id"]
    text_col = cols["text"]
    date_col = cols["note_date"]
    ref_col = cols["source_ref"]

    patient_cache: dict[str, str] = {}
    upserted = 0

    for row in rows:
        patient_id_ext = str(row.get(pid_col, "")).strip()
        text_id = str(row.get(text_id_col, "")).strip()
        note_text = str(row.get(text_col, "")).strip()
        if not patient_id_ext or not text_id or not note_text:
            continue

        note_date = None
        if date_col and row.get(date_col):
            try:
                note_date = datetime.fromisoformat(str(row[date_col]).strip())
            except (ValueError, TypeError):
                pass
        if note_date is None:
            continue

        if patient_id_ext not in patient_cache:
            patient = await _get_or_create_patient(
                session, project_id, patient_id_ext, data_source_id
            )
            patient_cache[patient_id_ext] = patient.id
        patient_db_id = patient_cache[patient_id_ext]

        source_ref = str(row[ref_col]) if ref_col and row.get(ref_col) else None

        existing = await session.execute(
            select(Note).where(
                Note.project_id == project_id,
                Note.text_id == text_id,
            )
        )
        existing_note = existing.scalar_one_or_none()

        if existing_note:
            existing_note.text = note_text
            existing_note.note_date = note_date
            if source_ref is not None:
                existing_note.source_ref = source_ref
            session.add(existing_note)
        else:
            known_cols = {pid_col, text_id_col, text_col, date_col, ref_col}
            extra = {k: v for k, v in row.items() if k not in known_cols and k is not None}
            note = Note(
                project_id=project_id,
                patient_id=patient_db_id,
                text_id=text_id,
                note_date=note_date,
                text=note_text,
                source_ref=source_ref,
                data_source_id=data_source_id,
                metadata_=extra,
            )
            session.add(note)
        upserted += 1

    await session.flush()
    return upserted


async def purge_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> int:
    """Delete all patients, notes, sentences, and annotations from a data source.

    Returns count of deleted notes.
    """
    from sqlalchemy import delete

    from app.annotations.models import Annotation
    from app.nlp.models import Sentence

    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise ValueError("Data source not found")

    note_ids_stmt = select(Note.id).where(
        Note.project_id == project_id,
        Note.data_source_id == data_source_id,
    )
    note_ids = [r[0] for r in (await session.execute(note_ids_stmt)).all()]

    if not note_ids:
        return 0

    await session.execute(
        delete(Annotation).where(Annotation.note_id.in_(note_ids))
    )
    await session.execute(
        delete(Sentence).where(Sentence.note_id.in_(note_ids))
    )
    await session.execute(
        delete(Note).where(Note.id.in_(note_ids))
    )

    patient_ids_stmt = select(Patient.id).where(
        Patient.project_id == project_id,
        Patient.data_source_id == data_source_id,
    )
    for pid in [r[0] for r in (await session.execute(patient_ids_stmt)).all()]:
        remaining = (
            await session.execute(
                select(func.count()).select_from(Note).where(Note.patient_id == pid)
            )
        ).scalar() or 0
        if remaining == 0:
            await session.execute(delete(Patient).where(Patient.id == pid))

    ds.status = IngestionStatus.PENDING
    ds.row_count = None
    ds.last_sync = None
    session.add(ds)
    await session.commit()

    await log_action(
        session, project_id, AuditAction.DATA_PURGED,
        detail={"data_source_id": data_source_id, "deleted_notes": len(note_ids)},
    )

    return len(note_ids)


async def _ingest_rows(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    rows: list[dict],
    column_mapping: dict,
) -> int:
    """Insert a batch of rows as patients and notes. Returns count of inserted rows."""
    cols = _normalize_columns(rows, column_mapping)
    pid_col = cols["patient_id"]
    text_id_col = cols["text_id"]
    text_col = cols["text"]
    date_col = cols["note_date"]
    ref_col = cols["source_ref"]

    # Batch duplicate check: collect all text_ids, query once
    all_text_ids = [str(row.get(text_id_col, "")).strip() for row in rows]
    all_text_ids = [tid for tid in all_text_ids if tid]
    existing_result = await session.execute(
        select(Note.text_id).where(
            Note.project_id == project_id,
            Note.text_id.in_(all_text_ids),
        )
    )
    existing_text_ids: set[str] = {r[0] for r in existing_result.all()}

    # Cache patient lookups within the batch
    patient_cache: dict[str, str] = {}
    inserted = 0

    for row in rows:
        patient_id_ext = str(row.get(pid_col, "")).strip()
        text_id = str(row.get(text_id_col, "")).strip()
        note_text = str(row.get(text_col, "")).strip()
        if not patient_id_ext or not text_id or not note_text:
            continue

        # Skip duplicate text_ids (already ingested) — in-memory check
        if text_id in existing_text_ids:
            continue

        # Get or create patient
        if patient_id_ext not in patient_cache:
            patient = await _get_or_create_patient(
                session, project_id, patient_id_ext, data_source_id
            )
            patient_cache[patient_id_ext] = patient.id
        patient_db_id = patient_cache[patient_id_ext]

        # Parse note_date (required)
        note_date = None
        if date_col and row.get(date_col):
            try:
                note_date = datetime.fromisoformat(str(row[date_col]).strip())
            except (ValueError, TypeError):
                pass
        if note_date is None:
            logger.warning("Skipping row with text_id=%s: missing or invalid note_date", text_id)
            continue

        source_ref = str(row[ref_col]) if ref_col and row.get(ref_col) else None

        # Collect remaining columns as metadata
        known_cols = {pid_col, text_id_col, text_col, date_col, ref_col}
        extra = {k: v for k, v in row.items() if k not in known_cols and k is not None}

        note = Note(
            project_id=project_id,
            patient_id=patient_db_id,
            text_id=text_id,
            note_date=note_date,
            text=note_text,
            source_ref=source_ref,
            data_source_id=data_source_id,
            metadata_=extra,
        )
        session.add(note)
        inserted += 1

    await session.flush()

    if inserted == 0 and rows:
        available_cols = list(rows[0].keys()) if rows else []
        logger.warning(
            "Ingestion inserted 0 rows from %d. CSV columns: %s, mapping: %s",
            len(rows),
            available_cols,
            {
                "patient_id": pid_col,
                "text_id": text_id_col,
                "text": text_col,
            },
        )

    return inserted


async def _get_or_create_patient(
    session: AsyncSession,
    project_id: str,
    patient_id_ext: str,
    data_source_id: str,
) -> Patient:
    """Find existing patient or create a new one."""
    stmt = select(Patient).where(
        Patient.project_id == project_id,
        Patient.patient_id_ext == patient_id_ext,
    )
    result = await session.execute(stmt)
    patient = result.scalar_one_or_none()
    if patient:
        return patient

    patient = Patient(
        project_id=project_id,
        patient_id_ext=patient_id_ext,
        data_source_id=data_source_id,
    )
    session.add(patient)
    await session.flush()
    return patient


# ── Patient + Note queries ────────────────────────────────────────


async def list_patients(
    session: AsyncSession,
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
) -> dict:
    """List patients with note counts, optional search and status filter."""
    base_where = [Patient.project_id == project_id, Patient.deleted_at.is_(None)]

    if search:
        base_where.append(Patient.patient_id_ext.ilike(f"%{search}%"))
    if status:
        base_where.append(Patient.status == status)

    # Count total matching
    count_stmt = select(func.count()).select_from(Patient).where(*base_where)
    total = (await session.execute(count_stmt)).scalar() or 0

    # Fetch page with note counts
    stmt = (
        select(
            Patient,
            func.count(Note.id).label("note_count"),
        )
        .outerjoin(Note, (Note.patient_id == Patient.id) & Note.deleted_at.is_(None))
        .where(*base_where)
        .group_by(Patient.id)
        .order_by(Patient.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = [
        {"patient": row[0], "note_count": row[1]}
        for row in result.all()
    ]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def get_patient_notes(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[Note]:
    stmt = (
        select(Note)
        .where(
            Note.project_id == project_id,
            Note.patient_id == patient_id,
            Note.deleted_at.is_(None),
        )
        .order_by(Note.note_date.desc(), Note.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
