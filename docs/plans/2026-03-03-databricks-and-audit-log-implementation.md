# Databricks Connector + Audit Log Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add bidirectional Databricks integration (import clinical notes, export results) and an append-only audit log with per-patient activity timeline.

**Architecture:** DatabricksConnector implements existing ConnectorBase ABC, registered in the plugin registry. Audit log is a new `audit_log` table with explicit `log_action()` calls from service functions. Data lifecycle endpoints (re-sync, purge) added to the connectors module. Databricks export added to the export module.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, databricks-sql-connector, Alembic, pytest + aiosqlite

**Design Doc:** `docs/plans/2026-03-03-databricks-connector-and-audit-log-design.md`

---

## Phase Overview

| Phase | Domain | Tasks |
|-------|--------|-------|
| **A** | Databricks connector (import) | Tasks 1-4 |
| **B** | Data lifecycle (re-sync + purge) | Tasks 5-6 |
| **C** | Audit log | Tasks 7-10 |
| **D** | Databricks export | Tasks 11-12 |

---

## Phase A: Databricks Connector (Import)

### Task 1: Add databricks-sql-connector dependency

**Files:**
- Modify: `backend/pyproject.toml:13-35` (add dependency)

**Step 1: Add the dependency**

Add `"databricks-sql-connector>=3.0.0"` to the `dependencies` list in `backend/pyproject.toml`, after the `httpx` line.

**Step 2: Install**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv sync`
Expected: Installs without errors.

**Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add databricks-sql-connector dependency"
```

---

### Task 2: Write DatabricksConnector tests

**Files:**
- Modify: `backend/tests/test_connectors.py` (add test class)

**Step 1: Write the failing tests**

Add to the end of `backend/tests/test_connectors.py`:

```python
from unittest.mock import MagicMock, patch

from app.connectors.databricks import DatabricksConnector


class TestDatabricksConnector:
    @pytest.fixture
    def connector(self):
        return DatabricksConnector()

    def test_required_columns(self, connector):
        cols = connector.required_columns()
        assert "patient_id" in cols
        assert "text_id" in cols
        assert "text" in cols
        assert "note_date" in cols

    async def test_validate_config_valid(self, connector):
        config = {
            "host": "adb-123.azuredatabricks.net",
            "http_path": "/sql/1.0/warehouses/abc",
            "token": "dapi-test-token",
            "catalog": "hive_metastore",
            "schema": "clinical",
            "table": "notes",
            "column_mapping": {
                "patient_id": "mrn",
                "text_id": "note_id",
                "text": "note_text",
                "note_date": "date_created",
            },
        }
        with patch("app.connectors.databricks.connect_databricks") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            errors = await connector.validate_config(config)
        assert errors == []

    async def test_validate_config_missing_fields(self, connector):
        config = {"host": "adb-123.azuredatabricks.net"}
        errors = await connector.validate_config(config)
        assert any("http_path" in e for e in errors)
        assert any("token" in e for e in errors)
        assert any("table" in e for e in errors)

    async def test_validate_config_missing_column_mapping(self, connector):
        config = {
            "host": "h",
            "http_path": "p",
            "token": "t",
            "schema": "s",
            "table": "tbl",
            "column_mapping": {},
        }
        errors = await connector.validate_config(config)
        assert any("patient_id" in e for e in errors)
        assert any("text_id" in e for e in errors)
        assert any("text" in e for e in errors)
        assert any("note_date" in e for e in errors)

    async def test_validate_config_connection_failure(self, connector):
        config = {
            "host": "bad-host",
            "http_path": "/sql/1.0/warehouses/abc",
            "token": "bad-token",
            "catalog": "hive_metastore",
            "schema": "clinical",
            "table": "notes",
            "column_mapping": {
                "patient_id": "mrn",
                "text_id": "note_id",
                "text": "note_text",
                "note_date": "date_created",
            },
        }
        with patch("app.connectors.databricks.connect_databricks", side_effect=Exception("Connection refused")):
            errors = await connector.validate_config(config)
        assert any("connect" in e.lower() for e in errors)

    async def test_preview(self, connector):
        config = {
            "host": "h",
            "http_path": "p",
            "token": "t",
            "catalog": "cat",
            "schema": "s",
            "table": "tbl",
            "column_mapping": {"patient_id": "mrn", "text_id": "nid", "text": "txt", "note_date": "dt"},
        }
        mock_rows = [
            {"mrn": "P001", "nid": "N001", "txt": "Note one", "dt": "2024-01-01"},
            {"mrn": "P002", "nid": "N002", "txt": "Note two", "dt": "2024-01-02"},
        ]
        with patch("app.connectors.databricks.connect_databricks") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.description = [("mrn",), ("nid",), ("txt",), ("dt",)]
            mock_cursor.fetchall.return_value = [
                ("P001", "N001", "Note one", "2024-01-01"),
                ("P002", "N002", "Note two", "2024-01-02"),
            ]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            result = await connector.preview(config, limit=5)
        assert result.columns == ["mrn", "nid", "txt", "dt"]
        assert len(result.rows) == 2
        assert result.rows[0]["mrn"] == "P001"

    async def test_fetch_batching(self, connector):
        config = {
            "host": "h",
            "http_path": "p",
            "token": "t",
            "catalog": "cat",
            "schema": "s",
            "table": "tbl",
            "column_mapping": {"patient_id": "mrn", "text_id": "nid", "text": "txt", "note_date": "dt"},
        }
        with patch("app.connectors.databricks.connect_databricks") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.description = [("mrn",), ("nid",), ("txt",), ("dt",)]
            # Return 2 rows for batch_size=2 (has_more=True)
            mock_cursor.fetchall.return_value = [
                ("P001", "N001", "Note one", "2024-01-01"),
                ("P002", "N002", "Note two", "2024-01-02"),
            ]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            result = await connector.fetch(config, batch_size=2, offset=0)
        assert len(result.rows) == 2
        assert result.has_more is True
        assert result.offset == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py::TestDatabricksConnector -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.connectors.databricks'`

**Step 3: Commit**

```bash
git add backend/tests/test_connectors.py
git commit -m "test: add DatabricksConnector unit tests"
```

---

### Task 3: Implement DatabricksConnector

**Files:**
- Create: `backend/app/connectors/databricks.py`

**Step 1: Implement the connector**

```python
"""Databricks SQL warehouse connector."""

import logging

from databricks import sql as databricks_sql

from app.connectors.base import ConnectorBase, FetchResult, PreviewResult

logger = logging.getLogger(__name__)


def connect_databricks(config: dict):
    """Create a Databricks SQL connection from config."""
    return databricks_sql.connect(
        server_hostname=config["host"],
        http_path=config["http_path"],
        access_token=config["token"],
    )


def _fqn(config: dict) -> str:
    """Build fully qualified table name: catalog.schema.table."""
    catalog = config.get("catalog", "hive_metastore")
    schema = config["schema"]
    table = config["table"]
    return f"`{catalog}`.`{schema}`.`{table}`"


class DatabricksConnector(ConnectorBase):
    """Connector for Databricks SQL warehouses.

    Config schema:
        {
            "host": "adb-123.azuredatabricks.net",
            "http_path": "/sql/1.0/warehouses/abcd1234",
            "token": "dapi...",
            "catalog": "hive_metastore",      # optional, defaults to hive_metastore
            "schema": "clinical_data",
            "table": "clinical_notes",
            "column_mapping": {
                "patient_id": "mrn",
                "text_id": "note_id",
                "text": "note_text",
                "note_date": "date_created"
            }
        }
    """

    async def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []

        # Required fields
        for field in ("host", "http_path", "token", "table"):
            if not config.get(field):
                errors.append(f"{field} is required")

        if not config.get("schema"):
            errors.append("schema is required")

        # Column mapping
        mapping = config.get("column_mapping", {})
        for col in ("patient_id", "text_id", "text", "note_date"):
            if col not in mapping:
                errors.append(f"column_mapping must include '{col}'")

        if errors:
            return errors

        # Test connection
        try:
            conn = connect_databricks(config)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
        except Exception as e:
            errors.append(f"Could not connect to Databricks: {e}")

        return errors

    async def preview(self, config: dict, limit: int = 10) -> PreviewResult:
        conn = connect_databricks(config)
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {_fqn(config)} LIMIT {int(limit)}")
            columns = [desc[0] for desc in cursor.description]
            raw_rows = cursor.fetchall()
            rows = [dict(zip(columns, row)) for row in raw_rows]
            cursor.close()

            # Get total count
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {_fqn(config)}")
            total = cursor.fetchone()[0]
            cursor.close()

            return PreviewResult(columns=columns, rows=rows, total_available=total)
        finally:
            conn.close()

    async def fetch(
        self, config: dict, batch_size: int = 1000, offset: int = 0
    ) -> FetchResult:
        conn = connect_databricks(config)
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT * FROM {_fqn(config)} LIMIT {int(batch_size)} OFFSET {int(offset)}"
            )
            columns = [desc[0] for desc in cursor.description]
            raw_rows = cursor.fetchall()
            rows = [dict(zip(columns, row)) for row in raw_rows]
            cursor.close()

            return FetchResult(
                rows=rows,
                has_more=len(rows) == batch_size,
                offset=offset,
            )
        finally:
            conn.close()

    def required_columns(self) -> list[str]:
        return ["patient_id", "text_id", "text", "note_date"]
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py::TestDatabricksConnector -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/app/connectors/databricks.py
git commit -m "feat: implement DatabricksConnector with PAT auth"
```

---

### Task 4: Register DatabricksConnector in registry

**Files:**
- Modify: `backend/app/connectors/registry.py:28-35` (register in builtins)
- Modify: `backend/tests/test_connectors.py:68-79` (update registry tests)

**Step 1: Update the registry**

In `backend/app/connectors/registry.py`, modify `_register_builtins()`:

```python
def _register_builtins() -> None:
    """Register built-in connectors."""
    from app.connectors.file_upload import FileUploadConnector
    from app.connectors.databricks import DatabricksConnector

    register_connector(ConnectorType.FILE_UPLOAD, FileUploadConnector)
    register_connector(ConnectorType.DATABRICKS, DatabricksConnector)
```

**Step 2: Update the registry test**

In `backend/tests/test_connectors.py`, update `TestRegistry`:

```python
class TestRegistry:
    def test_file_upload_registered(self):
        types = list_connector_types()
        assert "file_upload" in types

    def test_databricks_registered(self):
        types = list_connector_types()
        assert "databricks" in types

    def test_get_file_upload_connector(self):
        connector = get_connector(ConnectorType.FILE_UPLOAD)
        assert isinstance(connector, FileUploadConnector)

    def test_get_databricks_connector(self):
        from app.connectors.databricks import DatabricksConnector
        connector = get_connector(ConnectorType.DATABRICKS)
        assert isinstance(connector, DatabricksConnector)
```

Remove the old `test_get_unknown_connector_raises` test that expected `DATABRICKS` to raise.

**Step 3: Run all connector tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add backend/app/connectors/registry.py backend/tests/test_connectors.py
git commit -m "feat: register DatabricksConnector in connector registry"
```

---

## Phase B: Data Lifecycle (Re-sync + Purge)

### Task 5: Add re-sync endpoint

**Files:**
- Modify: `backend/app/connectors/service.py` (add `resync_data_source` function)
- Modify: `backend/app/connectors/router.py` (add route)
- Modify: `backend/tests/test_connectors.py` (add tests)

**Step 1: Write the failing test**

Add to `backend/tests/test_connectors.py`:

```python
class TestResync:
    async def test_resync_upserts_existing_notes(self):
        """Resync should update existing notes (matched by text_id) and add new ones."""
        from app.connectors.service import create_data_source, run_ingestion, resync_data_source
        from app.connectors.models import ConnectorType, Note

        # This is a unit-level test — needs a session fixture
        # For now, test the function signature exists and is importable
        assert callable(resync_data_source)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py::TestResync -v`
Expected: FAIL — `ImportError: cannot import name 'resync_data_source'`

**Step 3: Implement resync in service**

Add to `backend/app/connectors/service.py` after `run_ingestion`:

```python
async def resync_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> DataSource:
    """Re-fetch data from connector. Update existing notes by text_id, insert new ones."""
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
            inserted = await _upsert_rows(session, project_id, ds.id, batch.rows, mapping)
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


async def _upsert_rows(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    rows: list[dict],
    column_mapping: dict,
) -> int:
    """Insert new rows or update existing ones (matched by text_id)."""
    pid_col = column_mapping.get("patient_id", "patient_id")
    text_id_col = column_mapping.get("text_id", "text_id")
    text_col = column_mapping.get("text", "text")
    date_col = column_mapping.get("note_date")
    ref_col = column_mapping.get("source_ref")

    if rows:
        actual_keys = list(rows[0].keys())
        norm_lookup: dict[str, str] = {}
        for key in actual_keys:
            normalized = key.strip().lower().replace(" ", "_")
            norm_lookup[normalized] = key

        def resolve(mapped_name: str | None) -> str | None:
            if mapped_name is None:
                return None
            if rows and mapped_name in rows[0]:
                return mapped_name
            normalized = mapped_name.strip().lower().replace(" ", "_")
            return norm_lookup.get(normalized, mapped_name)

        pid_col = resolve(pid_col) or pid_col
        text_id_col = resolve(text_id_col) or text_id_col
        text_col = resolve(text_col) or text_col
        date_col = resolve(date_col)
        ref_col = resolve(ref_col)

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

        # Get or create patient
        if patient_id_ext not in patient_cache:
            patient = await _get_or_create_patient(
                session, project_id, patient_id_ext, data_source_id
            )
            patient_cache[patient_id_ext] = patient.id
        patient_db_id = patient_cache[patient_id_ext]

        source_ref = str(row[ref_col]) if ref_col and row.get(ref_col) else None

        # Check for existing note
        existing = await session.execute(
            select(Note).where(
                Note.project_id == project_id,
                Note.text_id == text_id,
            )
        )
        existing_note = existing.scalar_one_or_none()

        if existing_note:
            # Update existing
            existing_note.text = note_text
            existing_note.note_date = note_date
            if source_ref is not None:
                existing_note.source_ref = source_ref
            session.add(existing_note)
        else:
            # Insert new
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
```

**Step 4: Add the route**

Add to `backend/app/connectors/router.py` after the `ingest` endpoint:

```python
@router.post("/sources/{data_source_id}/resync", response_model=IngestionResponse)
async def resync_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Re-sync a data source: update existing notes, add new ones."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    from app.connectors.service import resync_data_source
    result = await resync_data_source(session, project_id, data_source_id)
    return IngestionResponse(
        data_source_id=result.id,
        status=result.status,
        message=f"Re-synced {result.row_count or 0} rows" if result.row_count else result.error_message or "No data",
    )
```

**Step 5: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/connectors/service.py backend/app/connectors/router.py backend/tests/test_connectors.py
git commit -m "feat: add data source re-sync with upsert semantics"
```

---

### Task 6: Add purge endpoint

**Files:**
- Modify: `backend/app/connectors/service.py` (add `purge_data_source` function)
- Modify: `backend/app/connectors/router.py` (add route)
- Modify: `backend/tests/test_connectors.py` (add test)

**Step 1: Write the failing test**

Add to `backend/tests/test_connectors.py`:

```python
class TestPurge:
    async def test_purge_function_exists(self):
        from app.connectors.service import purge_data_source
        assert callable(purge_data_source)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py::TestPurge -v`
Expected: FAIL — `ImportError`

**Step 3: Implement purge in service**

Add to `backend/app/connectors/service.py`:

```python
async def purge_data_source(
    session: AsyncSession, project_id: str, data_source_id: str
) -> int:
    """Delete all patients, notes, sentences, and annotations from a data source.

    Returns count of deleted notes.
    """
    from app.annotations.models import Annotation
    from app.nlp.models import Sentence

    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise ValueError("Data source not found")

    # Get all note IDs for this data source
    note_ids_stmt = select(Note.id).where(
        Note.project_id == project_id,
        Note.data_source_id == data_source_id,
    )
    note_ids = [r[0] for r in (await session.execute(note_ids_stmt)).all()]

    if not note_ids:
        return 0

    # Delete annotations referencing these notes
    from sqlalchemy import delete
    await session.execute(
        delete(Annotation).where(Annotation.note_id.in_(note_ids))
    )

    # Delete sentences referencing these notes
    await session.execute(
        delete(Sentence).where(Sentence.note_id.in_(note_ids))
    )

    # Delete notes
    await session.execute(
        delete(Note).where(Note.id.in_(note_ids))
    )

    # Delete patients that have no remaining notes
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

    # Reset data source status
    ds.status = IngestionStatus.PENDING
    ds.row_count = None
    ds.last_sync = None
    session.add(ds)
    await session.commit()

    return len(note_ids)
```

**Step 4: Add the route**

Add to `backend/app/connectors/router.py`:

```python
@router.delete("/sources/{data_source_id}/data")
async def purge_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    confirm: bool = False,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Purge all data (patients, notes, sentences, annotations) from a data source."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm data deletion",
        )

    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    from app.connectors.service import purge_data_source
    deleted = await purge_data_source(session, project_id, data_source_id)
    return {"deleted_notes": deleted, "data_source_id": data_source_id}
```

**Step 5: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/connectors/service.py backend/app/connectors/router.py backend/tests/test_connectors.py
git commit -m "feat: add data source purge endpoint with cascade delete"
```

---

## Phase C: Audit Log

### Task 7: Create AuditEntry model and migration

**Files:**
- Create: `backend/app/audit/__init__.py`
- Create: `backend/app/audit/models.py`
- Modify: `backend/migrations/env.py` (import new model)

**Step 1: Write the failing test**

Add to a new file `backend/tests/test_audit.py`:

```python
"""Tests for audit log models and service."""

from app.audit.models import AuditAction, AuditEntry


class TestAuditModels:
    def test_audit_action_values(self):
        assert AuditAction.ANNOTATION_REVIEWED.value == "annotation_reviewed"
        assert AuditAction.PATIENT_LOCKED.value == "patient_locked"
        assert AuditAction.DATA_INGESTED.value == "data_ingested"

    def test_audit_entry_defaults(self):
        entry = AuditEntry(
            project_id="proj1",
            action=AuditAction.ANNOTATION_REVIEWED,
            user_id="user1",
        )
        assert entry.patient_id is None
        assert entry.detail == {}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the model**

Create `backend/app/audit/__init__.py` (empty file).

Create `backend/app/audit/models.py`:

```python
"""Audit log models."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, Index
from sqlmodel import Field, SQLModel


class AuditAction(str, enum.Enum):
    """Auditable actions in the system."""

    # Annotation actions
    ANNOTATION_REVIEWED = "annotation_reviewed"
    ANNOTATION_SKIPPED = "annotation_skipped"
    EVENT_DATE_SET = "event_date_set"
    EVENT_DATE_DELETED = "event_date_deleted"

    # Patient actions
    PATIENT_LOCKED = "patient_locked"
    PATIENT_UNLOCKED = "patient_unlocked"
    PATIENT_REOPENED = "patient_reopened"

    # Model actions
    PREDICTION_RAN = "prediction_ran"
    AUTO_ADJUDICATED = "auto_adjudicated"

    # Data actions
    DATA_INGESTED = "data_ingested"
    DATA_PURGED = "data_purged"
    DATA_RESYNCED = "data_resynced"


class AuditEntry(SQLModel, table=True):
    """Append-only audit log entry."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_project_patient", "project_id", "patient_id"),
        Index("ix_audit_project_created", "project_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str | None = Field(default=None, foreign_key="patients.id")
    user_id: str | None = Field(default=None, foreign_key="users.id")
    action: AuditAction
    detail: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
```

**Step 4: Add model import to migrations/env.py**

In `backend/migrations/env.py`, add alongside the other model imports:

```python
from app.audit.models import AuditEntry  # noqa: E402, F401
```

**Step 5: Run test to verify it passes**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_audit.py -v`
Expected: PASS

**Step 6: Generate Alembic migration**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run alembic revision --autogenerate -m "add audit_log table"`

Verify the generated migration creates the `audit_log` table with expected columns and indexes.

**Step 7: Apply migration**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run alembic upgrade head`
Expected: No errors (requires PostgreSQL running via docker-compose.v2.yml).

**Step 8: Commit**

```bash
git add backend/app/audit/ backend/migrations/ backend/tests/test_audit.py
git commit -m "feat: add audit_log table with AuditEntry model and migration"
```

---

### Task 8: Implement audit service (log_action + queries)

**Files:**
- Create: `backend/app/audit/service.py`
- Modify: `backend/tests/test_audit.py` (add service tests)

**Step 1: Write the failing test**

Add to `backend/tests/test_audit.py`:

```python
from app.audit.service import log_action, get_patient_activity, query_audit_log


class TestAuditService:
    async def test_log_action_importable(self):
        assert callable(log_action)

    async def test_get_patient_activity_importable(self):
        assert callable(get_patient_activity)

    async def test_query_audit_log_importable(self):
        assert callable(query_audit_log)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_audit.py::TestAuditService -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the service**

Create `backend/app/audit/service.py`:

```python
"""Audit log service: write entries and query history."""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditEntry

logger = logging.getLogger(__name__)


async def log_action(
    session: AsyncSession,
    project_id: str,
    action: AuditAction,
    user_id: str | None = None,
    patient_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append an audit entry. Fire-and-forget — logs but never raises."""
    try:
        entry = AuditEntry(
            project_id=project_id,
            action=action,
            user_id=user_id,
            patient_id=patient_id,
            detail=detail or {},
        )
        session.add(entry)
        await session.flush()
    except Exception:
        logger.exception("Failed to write audit entry: %s %s", action, detail)


async def get_patient_activity(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    limit: int = 100,
) -> dict:
    """Get activity timeline for a specific patient."""
    from app.auth.models import User

    stmt = (
        select(AuditEntry, User.name)
        .outerjoin(User, AuditEntry.user_id == User.id)
        .where(
            AuditEntry.project_id == project_id,
            AuditEntry.patient_id == patient_id,
        )
        .order_by(AuditEntry.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()

    # Summary: unique users and total actions
    unique_users: set[str] = set()
    entries = []
    for entry, user_name in rows:
        display_name = user_name or "System"
        unique_users.add(display_name)
        entries.append({
            "id": entry.id,
            "action": entry.action.value,
            "user_name": display_name,
            "user_id": entry.user_id,
            "detail": entry.detail,
            "created_at": entry.created_at.isoformat(),
        })

    return {
        "patient_id": patient_id,
        "summary": {
            "total_actions": len(entries),
            "unique_users": len(unique_users),
            "users": sorted(unique_users),
        },
        "entries": entries,
    }


async def query_audit_log(
    session: AsyncSession,
    project_id: str,
    patient_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Query audit log with filters. Admin use."""
    from app.auth.models import User

    conditions = [AuditEntry.project_id == project_id]
    if patient_id:
        conditions.append(AuditEntry.patient_id == patient_id)
    if user_id:
        conditions.append(AuditEntry.user_id == user_id)
    if action:
        conditions.append(AuditEntry.action == action)
    if since:
        conditions.append(AuditEntry.created_at >= since)
    if until:
        conditions.append(AuditEntry.created_at <= until)

    # Count
    count_stmt = select(func.count()).select_from(AuditEntry).where(*conditions)
    total = (await session.execute(count_stmt)).scalar() or 0

    # Fetch page
    stmt = (
        select(AuditEntry, User.name)
        .outerjoin(User, AuditEntry.user_id == User.id)
        .where(*conditions)
        .order_by(AuditEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)

    entries = []
    for entry, user_name in result.all():
        entries.append({
            "id": entry.id,
            "action": entry.action.value,
            "user_name": user_name or "System",
            "user_id": entry.user_id,
            "patient_id": entry.patient_id,
            "detail": entry.detail,
            "created_at": entry.created_at.isoformat(),
        })

    return {"items": entries, "total": total, "limit": limit, "offset": offset}
```

**Step 4: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_audit.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/audit/service.py backend/tests/test_audit.py
git commit -m "feat: implement audit log service (log_action, queries)"
```

---

### Task 9: Add audit API router

**Files:**
- Create: `backend/app/audit/router.py`
- Modify: `backend/app/main.py:14` (register router)

**Step 1: Implement the router**

Create `backend/app/audit/router.py`:

```python
"""API routes for audit log."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.audit.service import get_patient_activity, query_audit_log

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["audit"],
)


@router.get("/audit")
async def query_audit_endpoint(
    project_id: str,
    patient_id: str | None = Query(None),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Query audit log entries with filters. Admin only."""
    return await query_audit_log(
        session, project_id,
        patient_id=patient_id,
        user_id=user_id,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/patients/{patient_id}/activity")
async def patient_activity_endpoint(
    project_id: str,
    patient_id: str,
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get activity timeline for a patient."""
    return await get_patient_activity(session, project_id, patient_id, limit=limit)
```

**Step 2: Register in main.py**

In `backend/app/main.py`, add the import and include:

```python
from app.audit.router import router as audit_router
```

And in `create_app()`:

```python
application.include_router(audit_router)
```

**Step 3: Run full test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add backend/app/audit/router.py backend/app/main.py
git commit -m "feat: add audit log API endpoints (query, patient activity)"
```

---

### Task 10: Wire audit logging into existing services

**Files:**
- Modify: `backend/app/annotations/service.py` (add log_action calls)
- Modify: `backend/app/connectors/service.py` (add log_action calls)

**Step 1: Add audit logging to annotation service**

In `backend/app/annotations/service.py`, add import at top:

```python
from app.audit.models import AuditAction
from app.audit.service import log_action
```

Add `log_action` calls to:

1. `review_annotation` — after commit, before return:
```python
await log_action(
    session, project_id, AuditAction.ANNOTATION_REVIEWED,
    user_id=user_id, patient_id=annotation.patient_id,
    detail={"annotation_id": annotation_id, "event_date": event_date.isoformat() if event_date else None},
)
if event_date:
    await log_action(
        session, project_id, AuditAction.EVENT_DATE_SET,
        user_id=user_id, patient_id=annotation.patient_id,
        detail={"annotation_id": annotation_id, "event_date": event_date.isoformat()},
    )
```

2. `skip_annotation` — after commit:
```python
await log_action(
    session, project_id, AuditAction.ANNOTATION_SKIPPED,
    user_id=user_id, patient_id=annotation.patient_id,
    detail={"annotation_id": annotation_id},
)
```

3. `get_next_patient_for_review` — after locking:
```python
await log_action(
    session, project_id, AuditAction.PATIENT_LOCKED,
    user_id=user_id, patient_id=patient.id,
)
```

4. `unlock_patient` — after commit:
```python
await log_action(
    session, project_id, AuditAction.PATIENT_UNLOCKED,
    user_id=user_id, patient_id=patient_id,
)
```

5. `delete_event_date` — after commit:
```python
await log_action(
    session, project_id, AuditAction.EVENT_DATE_DELETED,
    user_id=user_id, patient_id=annotation.patient_id,
    detail={"annotation_id": annotation_id},
)
```

**Step 2: Add audit logging to connectors service**

In `backend/app/connectors/service.py`, add import:

```python
from app.audit.models import AuditAction
from app.audit.service import log_action
```

Add `log_action` calls to:

1. `run_ingestion` — after successful completion:
```python
await log_action(
    session, project_id, AuditAction.DATA_INGESTED,
    detail={"data_source_id": data_source_id, "row_count": total_rows},
)
```

2. `resync_data_source` — after successful completion:
```python
await log_action(
    session, project_id, AuditAction.DATA_RESYNCED,
    detail={"data_source_id": data_source_id, "row_count": total_rows},
)
```

3. `purge_data_source` — after deletion:
```python
await log_action(
    session, project_id, AuditAction.DATA_PURGED,
    detail={"data_source_id": data_source_id, "deleted_notes": len(note_ids)},
)
```

**Step 3: Run full test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: ALL PASS (log_action is fire-and-forget, doesn't break existing behavior)

**Step 4: Commit**

```bash
git add backend/app/annotations/service.py backend/app/connectors/service.py
git commit -m "feat: wire audit logging into annotation and connector services"
```

---

## Phase D: Databricks Export

### Task 11: Implement Databricks export service

**Files:**
- Create: `backend/app/export/databricks.py`
- Modify: `backend/app/export/schemas.py` (add export request schema)

**Step 1: Write the failing test**

Add to a new file `backend/tests/test_export_databricks.py`:

```python
"""Tests for Databricks export."""

from unittest.mock import MagicMock, patch

import pytest

from app.export.databricks import export_to_databricks, ExportType


class TestDatabricksExport:
    def test_export_type_values(self):
        assert ExportType.ANNOTATIONS.value == "annotations"
        assert ExportType.PREDICTIONS.value == "predictions"
        assert ExportType.EVALUATION.value == "evaluation"

    async def test_export_function_exists(self):
        assert callable(export_to_databricks)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_export_databricks.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Add export request schema**

Add to `backend/app/export/schemas.py`:

```python
class DatabricksExportRequest(BaseModel):
    data_source_id: str
    target_table: str
    export_type: str  # "annotations", "predictions", "evaluation"


class DatabricksExportResponse(BaseModel):
    rows_exported: int
    target_table: str
    status: str
```

**Step 4: Implement the export service**

Create `backend/app/export/databricks.py`:

```python
"""Export project results to a Databricks table."""

import enum
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.connectors.models import DataSource, Note
from app.connectors.databricks import connect_databricks, _fqn

logger = logging.getLogger(__name__)


class ExportType(str, enum.Enum):
    ANNOTATIONS = "annotations"
    PREDICTIONS = "predictions"
    EVALUATION = "evaluation"


# Column definitions per export type
SCHEMAS = {
    ExportType.ANNOTATIONS: [
        ("patient_id", "STRING"),
        ("text_id", "STRING"),
        ("sentence_text", "STRING"),
        ("review_status", "STRING"),
        ("event_date", "TIMESTAMP"),
        ("reviewer", "STRING"),
        ("reviewed_at", "TIMESTAMP"),
    ],
    ExportType.PREDICTIONS: [
        ("patient_id", "STRING"),
        ("text_id", "STRING"),
        ("sentence_text", "STRING"),
        ("predictor_name", "STRING"),
        ("score", "DOUBLE"),
        ("label", "INT"),
        ("reasoning", "STRING"),
    ],
    ExportType.EVALUATION: [
        ("session_name", "STRING"),
        ("note_text_id", "STRING"),
        ("prediction_label", "INT"),
        ("human_judgment", "STRING"),
        ("predictor_config", "STRING"),
    ],
}


async def export_to_databricks(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    target_table: str,
    export_type: ExportType,
) -> int:
    """Export project data to a Databricks table.

    Uses the connection config from the specified data source.
    Returns the number of rows exported.
    """
    # Get data source config for Databricks connection
    ds = (
        await session.execute(
            select(DataSource).where(
                DataSource.id == data_source_id,
                DataSource.project_id == project_id,
            )
        )
    ).scalar_one_or_none()

    if not ds:
        raise ValueError("Data source not found")

    config = ds.config

    # Override table name with target
    export_config = {**config, "table": target_table}

    # Fetch rows from PostgreSQL
    rows = await _fetch_export_rows(session, project_id, export_type)
    if not rows:
        return 0

    # Write to Databricks
    schema = SCHEMAS[export_type]
    conn = connect_databricks(export_config)
    try:
        cursor = conn.cursor()

        # Create table if not exists
        col_defs = ", ".join(f"`{name}` {dtype}" for name, dtype in schema)
        fqn = _fqn(export_config)
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {fqn} ({col_defs})")

        # Insert rows in batches
        col_names = ", ".join(f"`{name}`" for name, _ in schema)
        placeholders = ", ".join("?" for _ in schema)
        insert_sql = f"INSERT INTO {fqn} ({col_names}) VALUES ({placeholders})"

        batch_size = 1000
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            for row in batch:
                cursor.execute(insert_sql, row)

        cursor.close()
    finally:
        conn.close()

    return len(rows)


async def _fetch_export_rows(
    session: AsyncSession,
    project_id: str,
    export_type: ExportType,
) -> list[tuple]:
    """Fetch rows from PostgreSQL for export."""
    if export_type == ExportType.ANNOTATIONS:
        return await _fetch_annotation_rows(session, project_id)
    elif export_type == ExportType.PREDICTIONS:
        return await _fetch_prediction_rows(session, project_id)
    elif export_type == ExportType.EVALUATION:
        return await _fetch_evaluation_rows(session, project_id)
    return []


async def _fetch_annotation_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    stmt = (
        select(Annotation, Note.text_id)
        .join(Note, Annotation.note_id == Note.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.review_status != ReviewStatus.UNREVIEWED,
        )
    )
    result = await session.execute(stmt)
    rows = []
    for ann, text_id in result.all():
        rows.append((
            ann.patient_id,
            text_id,
            ann.sentence_text,
            ann.review_status.value,
            ann.event_date,
            ann.reviewed_by or "",
            ann.reviewed_at,
        ))
    return rows


async def _fetch_prediction_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    stmt = (
        select(Annotation, Note.text_id)
        .join(Note, Annotation.note_id == Note.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.predicted_label.isnot(None),
        )
    )
    result = await session.execute(stmt)
    rows = []
    for ann, text_id in result.all():
        rows.append((
            ann.patient_id,
            text_id,
            ann.sentence_text,
            ann.predictor_model,
            ann.predicted_score,
            ann.predicted_label,
            ann.reasoning,
        ))
    return rows


async def _fetch_evaluation_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    from app.evaluation.models import EvaluationJudgment, EvaluationSession

    stmt = (
        select(EvaluationJudgment, EvaluationSession.name)
        .join(EvaluationSession, EvaluationJudgment.session_id == EvaluationSession.id)
        .where(EvaluationSession.project_id == project_id)
    )
    result = await session.execute(stmt)
    rows = []
    for judgment, session_name in result.all():
        rows.append((
            session_name,
            judgment.note_id,
            judgment.predicted_label,
            judgment.human_judgment,
            judgment.predictor_config_id or "",
        ))
    return rows
```

**Step 5: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_export_databricks.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/app/export/databricks.py backend/app/export/schemas.py backend/tests/test_export_databricks.py
git commit -m "feat: implement Databricks export service for annotations, predictions, evaluations"
```

---

### Task 12: Add Databricks export endpoint

**Files:**
- Modify: `backend/app/export/router.py` (add endpoint)

**Step 1: Add the route**

Add to `backend/app/export/router.py`:

```python
from app.export.schemas import DatabricksExportRequest, DatabricksExportResponse


@router.post("/databricks", response_model=DatabricksExportResponse)
async def export_to_databricks_endpoint(
    project_id: str,
    body: DatabricksExportRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Export project results to a Databricks table."""
    from app.export.databricks import ExportType, export_to_databricks

    try:
        export_type = ExportType(body.export_type)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid export_type. Must be one of: {[e.value for e in ExportType]}",
        )

    rows_exported = await export_to_databricks(
        session, project_id, body.data_source_id, body.target_table, export_type,
    )
    return DatabricksExportResponse(
        rows_exported=rows_exported,
        target_table=body.target_table,
        status="completed",
    )
```

**Step 2: Run full test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add backend/app/export/router.py
git commit -m "feat: add Databricks export API endpoint"
```

---

## Final Verification

### Task 13: Run full test suite and verify

**Step 1: Run all backend tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v --tb=short`
Expected: ALL PASS

**Step 2: Run linter**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run ruff check app/ tests/`
Expected: No errors (or only pre-existing warnings)

**Step 3: Verify new endpoints in OpenAPI docs**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run uvicorn app.main:app --port 8000 &`

Check `http://localhost:8000/docs` for new endpoints:
- `POST /api/v1/projects/{id}/data/sources/{id}/resync`
- `DELETE /api/v1/projects/{id}/data/sources/{id}/data`
- `GET /api/v1/projects/{id}/audit`
- `GET /api/v1/projects/{id}/patients/{id}/activity`
- `POST /api/v1/projects/{id}/export/databricks`
