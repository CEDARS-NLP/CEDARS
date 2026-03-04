"""File upload connector — reads CSV/JSON files from S3."""

import csv
import io
import json

from app.common.s3 import download_file
from app.connectors.base import ConnectorBase, FetchResult, PreviewResult


class FileUploadConnector(ConnectorBase):
    """Connector for files uploaded to S3 (CSV or JSON).

    Config schema:
        {
            "s3_key": "projects/{project_id}/uploads/{filename}",
            "file_type": "csv" | "json",
            "column_mapping": {
                "patient_id": "MRN",       # required
                "text_id": "note_id",       # required — unique note identifier
                "text": "note_text",        # required
                "note_date": "date",        # required
                "source_ref": "accession"   # optional
            }
        }
    """

    def __init__(self):
        self._cached_rows: list[dict] | None = None
        self._cached_key: str | None = None

    async def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if not config.get("s3_key"):
            errors.append("s3_key is required")
        file_type = config.get("file_type", "csv")
        if file_type not in ("csv", "json"):
            errors.append(f"Unsupported file_type: {file_type}")
        mapping = config.get("column_mapping", {})
        if "patient_id" not in mapping:
            errors.append("column_mapping must include 'patient_id'")
        if "text_id" not in mapping:
            errors.append("column_mapping must include 'text_id'")
        if "text" not in mapping:
            errors.append("column_mapping must include 'text'")
        if "note_date" not in mapping:
            errors.append("column_mapping must include 'note_date'")
        return errors

    async def preview(self, config: dict, limit: int = 10) -> PreviewResult:
        rows = self._get_rows(config)
        return PreviewResult(
            columns=list(rows[0].keys()) if rows else [],
            rows=rows[:limit],
            total_available=len(rows),
        )

    async def fetch(
        self, config: dict, batch_size: int = 1000, offset: int = 0
    ) -> FetchResult:
        rows = self._get_rows(config)
        batch = rows[offset : offset + batch_size]
        return FetchResult(
            rows=batch,
            has_more=(offset + batch_size) < len(rows),
            offset=offset,
        )

    def required_columns(self) -> list[str]:
        return ["patient_id", "text_id", "text", "note_date"]

    def _get_rows(self, config: dict) -> list[dict]:
        """Return parsed rows, caching to avoid re-downloading on each batch."""
        s3_key = config["s3_key"]
        if self._cached_key != s3_key or self._cached_rows is None:
            self._cached_rows = self._read_file(config)
            self._cached_key = s3_key
        return self._cached_rows

    def _read_file(self, config: dict) -> list[dict]:
        """Download from S3 and parse into list of dicts."""
        raw = download_file(config["s3_key"])
        file_type = config.get("file_type", "csv")
        if file_type == "json":
            return self._parse_json(raw)
        return self._parse_csv(raw)

    def _parse_csv(self, raw: bytes) -> list[dict]:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def _parse_json(self, raw: bytes) -> list[dict]:
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "records" in data:
            return data["records"]
        raise ValueError("JSON must be an array or an object with a 'records' key")
