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
