"""Databricks SQL warehouse connector."""

import asyncio
import logging
import re

from databricks import sql as databricks_sql

from app.connectors.base import ConnectorBase, FetchResult, PreviewResult

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_identifier(name: str, label: str) -> None:
    """Raise ValueError if name contains non-alphanumeric characters."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {label}: {name!r} — only alphanumeric and underscores allowed"
        )


def connect_databricks(config: dict):
    """Create a Databricks SQL connection from config."""
    from app.common.crypto import decrypt_value

    token = decrypt_value(config["token"])
    return databricks_sql.connect(
        server_hostname=config["host"],
        http_path=config["http_path"],
        access_token=token,
    )


def _fqn(config: dict) -> str:
    """Build fully qualified table name: catalog.schema.table."""
    catalog = config.get("catalog", "hive_metastore")
    schema = config["schema"]
    table = config["table"]
    _validate_identifier(catalog, "catalog")
    _validate_identifier(schema, "schema")
    _validate_identifier(table, "table")
    return f"`{catalog}`.`{schema}`.`{table}`"


def _test_connection(config: dict) -> str | None:
    """Test Databricks connection. Returns error message or None."""
    try:
        conn = connect_databricks(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return None
    except Exception as e:
        return f"Could not connect to Databricks: {e}"


def _preview_sync(config: dict, limit: int) -> PreviewResult:
    """Synchronous preview implementation."""
    conn = connect_databricks(config)
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {_fqn(config)} LIMIT {int(limit)}")
        columns = [desc[0] for desc in cursor.description]
        raw_rows = cursor.fetchall()
        rows = [dict(zip(columns, row)) for row in raw_rows]
        cursor.close()

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {_fqn(config)}")
        total = cursor.fetchone()[0]
        cursor.close()

        return PreviewResult(columns=columns, rows=rows, total_available=total)
    finally:
        conn.close()


def _fetch_sync(config: dict, batch_size: int, offset: int) -> FetchResult:
    """Synchronous fetch implementation."""
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


class DatabricksConnector(ConnectorBase):
    """Connector for Databricks SQL warehouses.

    Config schema:
        {
            "host": "adb-123.azuredatabricks.net",
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
    """

    async def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []

        for field in ("host", "http_path", "token", "table"):
            if not config.get(field):
                errors.append(f"{field} is required")

        if not config.get("schema"):
            errors.append("schema is required")

        # Validate identifier safety for SQL-interpolated fields
        for field in ("catalog", "schema", "table"):
            value = config.get(field)
            if value and not _IDENTIFIER_RE.match(value):
                errors.append(
                    f"Invalid {field}: {value!r} — only alphanumeric and underscores allowed"
                )

        mapping = config.get("column_mapping", {})
        for col in ("patient_id", "text_id", "text", "note_date"):
            if col not in mapping:
                errors.append(f"column_mapping must include '{col}'")

        if errors:
            return errors

        # Test connection in a thread to avoid blocking the event loop
        error = await asyncio.to_thread(_test_connection, config)
        if error:
            errors.append(error)

        return errors

    async def preview(self, config: dict, limit: int = 10) -> PreviewResult:
        return await asyncio.to_thread(_preview_sync, config, limit)

    async def fetch(
        self, config: dict, batch_size: int = 1000, offset: int = 0
    ) -> FetchResult:
        return await asyncio.to_thread(_fetch_sync, config, batch_size, offset)

    def required_columns(self) -> list[str]:
        return ["patient_id", "text_id", "text", "note_date"]
