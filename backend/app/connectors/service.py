"""Business logic for data sources, ingestion, patients, and notes."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.connectors.models import (
    ConnectorType,
    DataSource,
    IngestionStatus,
    Note,
    Patient,
)
from app.connectors.registry import get_connector


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


# ── Ingestion ─────────────────────────────────────────────────────


async def run_ingestion(
    session: AsyncSession, project_id: str, data_source_id: str
) -> DataSource:
    """Fetch data from connector and insert patients + notes in batches."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise ValueError("Data source not found")

    connector = get_connector(ds.connector_type)

    # Validate config
    errors = await connector.validate_config(ds.config)
    if errors:
        ds.status = IngestionStatus.FAILED
        ds.error_message = "; ".join(errors)
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
        return ds

    # Mark as running
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
            inserted = await _ingest_rows(session, project_id, ds.id, batch.rows, mapping)
            total_rows += inserted
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
    return ds


async def _ingest_rows(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    rows: list[dict],
    column_mapping: dict,
) -> int:
    """Insert a batch of rows as patients and notes. Returns count of inserted rows."""
    pid_col = column_mapping.get("patient_id", "patient_id")
    text_id_col = column_mapping.get("text_id", "text_id")
    text_col = column_mapping.get("text", "text")
    date_col = column_mapping.get("note_date")
    ref_col = column_mapping.get("source_ref")

    # Build a lookup from normalized (lowercase, stripped) column names to actual keys
    # so that "patient ID" matches a mapping value of "patient_id"
    if rows:
        actual_keys = list(rows[0].keys())
        norm_lookup: dict[str, str] = {}
        for key in actual_keys:
            normalized = key.strip().lower().replace(" ", "_")
            norm_lookup[normalized] = key

        def resolve(mapped_name: str | None) -> str | None:
            if mapped_name is None:
                return None
            # Try exact match first, then normalized
            if rows and mapped_name in rows[0]:
                return mapped_name
            normalized = mapped_name.strip().lower().replace(" ", "_")
            return norm_lookup.get(normalized, mapped_name)

        pid_col = resolve(pid_col) or pid_col
        text_id_col = resolve(text_id_col) or text_id_col
        text_col = resolve(text_col) or text_col
        date_col = resolve(date_col)
        ref_col = resolve(ref_col)

    # Cache patient lookups within the batch
    patient_cache: dict[str, str] = {}
    inserted = 0

    for row in rows:
        patient_id_ext = str(row.get(pid_col, "")).strip()
        text_id = str(row.get(text_id_col, "")).strip()
        note_text = str(row.get(text_col, "")).strip()
        if not patient_id_ext or not text_id or not note_text:
            continue

        # Skip duplicate text_ids (already ingested)
        existing = await session.execute(
            select(Note.id).where(
                Note.project_id == project_id,
                Note.text_id == text_id,
            )
        )
        if existing.scalar_one_or_none():
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
) -> list[dict]:
    """List patients with note counts."""
    stmt = (
        select(
            Patient,
            func.count(Note.id).label("note_count"),
        )
        .outerjoin(Note, (Note.patient_id == Patient.id) & Note.deleted_at.is_(None))
        .where(Patient.project_id == project_id, Patient.deleted_at.is_(None))
        .group_by(Patient.id)
        .order_by(Patient.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [
        {
            "patient": row[0],
            "note_count": row[1],
        }
        for row in result.all()
    ]


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
