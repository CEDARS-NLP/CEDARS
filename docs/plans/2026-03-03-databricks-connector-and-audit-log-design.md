# Databricks Connector + Audit Log Design

**Date:** 2026-03-03
**Branch:** `feature/v2-platform`
**Depends on:** Patient Browser implementation plan (same branch)

---

## 1. Databricks Connector (Task 3.3)

### Overview

Bidirectional Databricks integration: import clinical notes from a Databricks SQL warehouse into PostgreSQL for processing, and export results (annotations, predictions, evaluations) back to Databricks tables.

### Import: DatabricksConnector

**New file:** `backend/app/connectors/databricks.py`

Implements `ConnectorBase` using the `databricks-sql-connector` Python package. Registered in `registry.py` under `ConnectorType.DATABRICKS`.

**Config schema:**

```json
{
    "host": "adb-1234567890.12.azuredatabricks.net",
    "http_path": "/sql/1.0/warehouses/abcd1234",
    "token": "dapi...",
    "catalog": "hive_metastore",
    "schema": "clinical_data",
    "table": "clinical_notes",
    "column_mapping": {
        "patient_id": "mrn",
        "text_id": "note_id",
        "text": "note_text",
        "note_date": "date_created"
    }
}
```

**Authentication:** Personal Access Token (PAT) only.

**Methods:**

| Method | Behavior |
|--------|----------|
| `validate_config(config)` | Check required fields (host, http_path, token, schema, table), validate column_mapping has required keys, test connection with `SELECT 1` |
| `preview(config, limit=10)` | `SELECT * FROM catalog.schema.table LIMIT {limit}` |
| `fetch(config, batch_size, offset)` | `SELECT * FROM catalog.schema.table LIMIT {batch_size} OFFSET {offset}` |
| `required_columns()` | `["patient_id", "text_id", "text", "note_date"]` |

**Data flow:** Notes are copied into PostgreSQL (same as file upload). The DataSource record retains the full Databricks config for future re-sync or export.

### Data Lifecycle Endpoints

These work for any connector type, not just Databricks:

**Re-sync:** `POST /api/v1/projects/{id}/data/sources/{id}/resync`
- Re-runs ingestion with upsert semantics
- Updates existing notes (matched by `text_id`), inserts new ones
- Admin only
- Tracks sync history via `DataSource.last_sync`

**Purge:** `DELETE /api/v1/projects/{id}/data/sources/{id}/data`
- Deletes all patients, notes, sentences, and annotations tied to the data source
- Cascades via `data_source_id` FK
- Admin only, requires confirmation (frontend sends `?confirm=true`)

### Export to Databricks

**New endpoint:** `POST /api/v1/projects/{id}/export/databricks`

Writes project results to a Databricks table. Reuses Databricks connection config from the project's data source (no re-entering credentials).

**Request body:**

```json
{
    "data_source_id": "...",
    "target_table": "cedars_annotations",
    "export_type": "annotations"
}
```

**Export types and columns:**

| Type | Columns |
|------|---------|
| `annotations` | patient_id, text_id, sentence_text, review_status, event_date, reviewer, reviewed_at |
| `predictions` | patient_id, text_id, sentence_text, predictor_name, score, label, reasoning |
| `evaluation_judgments` | session_name, note_text_id, prediction_label, human_judgment, predictor_config |

**Behavior:** `CREATE TABLE IF NOT EXISTS` then `INSERT INTO` using `databricks-sql-connector`. Runs as a background job for large datasets.

### Dependency

Add `databricks-sql-connector>=3.0.0` to `backend/pyproject.toml`.

---

## 2. Audit Log (Task 9.2)

### Overview

Append-only audit log for clinical actions. Serves two purposes:
1. Per-patient activity timeline (displayed on patient detail page)
2. Admin compliance query (filterable by user, action, date)

### AuditEntry Model

**New file:** `backend/app/audit/models.py`

```
Table: audit_log
- id: str (UUID, PK)
- project_id: str (FK projects.id, indexed)
- patient_id: str | None (FK patients.id, indexed, nullable)
- user_id: str | None (FK users.id, nullable — null for system actions)
- action: AuditAction (enum)
- detail: dict (JSONB — action-specific payload)
- created_at: datetime (indexed, for time-range queries)
```

### Action Types

```python
class AuditAction(str, enum.Enum):
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
```

### Service Layer

**New file:** `backend/app/audit/service.py`

```python
async def log_action(
    session: AsyncSession,
    project_id: str,
    action: AuditAction,
    user_id: str | None = None,
    patient_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append an audit entry. Fire-and-forget — never raises."""
```

Called explicitly from service functions in:
- `annotations/service.py` — on review, skip, event date, lock/unlock
- `connectors/service.py` — on ingestion, purge, resync
- `evaluation/service.py` — on prediction runs
- `nlp/service.py` — on auto-adjudication

### API Endpoints

**New file:** `backend/app/audit/router.py`

| Endpoint | Description | Auth |
|----------|-------------|------|
| `GET /api/v1/projects/{id}/audit` | Query audit log (filters: patient_id, user_id, action, date range) | Admin |
| `GET /api/v1/projects/{id}/patients/{id}/activity` | Per-patient activity timeline | Admin, annotator |

**Activity timeline response:**

```json
{
    "patient_id": "...",
    "patient_id_ext": "MRN001",
    "summary": {
        "total_actions": 24,
        "unique_users": 3,
        "users": ["Dr. Smith", "Dr. Jones", "System"]
    },
    "entries": [
        {
            "action": "annotation_reviewed",
            "user_name": "Dr. Smith",
            "detail": {"annotation_id": "...", "review_status": "reviewed"},
            "created_at": "2026-03-03T10:30:00Z"
        }
    ]
}
```

### Patient Detail Page Integration

The patient detail page (from patient-browser plan) displays the activity timeline as a collapsible section showing:
- How many people touched this patient
- What actions were taken (annotations, predictions, locks)
- Timeline of events with user names and timestamps

---

## Design Decisions

1. **Copy notes into PG** — Databricks data is copied at ingestion time. PG is the working database for NLP, annotation, and evaluation. Re-sync and purge endpoints provide lifecycle management.

2. **Explicit logging over middleware** — Audit entries are written by service functions, not HTTP middleware. This gives precise action semantics (e.g., "annotation reviewed" not "POST to /review").

3. **Bidirectional Databricks** — Same connector config used for import and export. No credential duplication.

4. **Connector-agnostic lifecycle** — Re-sync and purge work for any connector type, not just Databricks.
