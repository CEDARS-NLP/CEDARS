"""Tests for data connector models, base ABC, and file upload connector."""

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.connectors.base import ConnectorBase, FetchResult, PreviewResult
from app.connectors.file_upload import FileUploadConnector
from app.connectors.models import (
    ConnectorType,
    DataSource,
    IngestionStatus,
    Note,
    Patient,
    PatientStatus,
)
from app.connectors.registry import get_connector, list_connector_types


# ── Model tests ───────────────────────────────────────────────────


class TestModels:
    def test_data_source_defaults(self):
        ds = DataSource(
            project_id="proj1",
            name="test.csv",
            connector_type=ConnectorType.FILE_UPLOAD,
        )
        assert ds.status == IngestionStatus.PENDING
        assert ds.config == {}
        assert ds.deleted_at is None
        assert ds.row_count is None

    def test_patient_defaults(self):
        p = Patient(project_id="proj1", patient_id_ext="MRN001")
        assert p.status == PatientStatus.NEW
        assert p.locked_by is None
        assert p.deleted_at is None

    def test_note_fields(self):
        n = Note(
            project_id="proj1",
            patient_id="pat1",
            text_id="NOTE001",
            text="Clinical note text",
            note_date=datetime(2024, 1, 15, tzinfo=UTC),
        )
        assert n.text == "Clinical note text"
        assert n.text_id == "NOTE001"
        assert n.note_date == datetime(2024, 1, 15, tzinfo=UTC)
        assert n.source_ref is None

    def test_connector_type_values(self):
        assert ConnectorType.FILE_UPLOAD.value == "file_upload"
        assert ConnectorType.DATABRICKS.value == "databricks"

    def test_patient_status_values(self):
        assert PatientStatus.NEW.value == "new"
        assert PatientStatus.REVIEWED.value == "reviewed"


# ── Registry tests ────────────────────────────────────────────────


class TestRegistry:
    def test_file_upload_registered(self):
        types = list_connector_types()
        assert "file_upload" in types

    def test_get_file_upload_connector(self):
        connector = get_connector(ConnectorType.FILE_UPLOAD)
        assert isinstance(connector, FileUploadConnector)

    def test_get_unknown_connector_raises(self):
        with pytest.raises(ValueError, match="Unknown connector type"):
            get_connector(ConnectorType.DATABRICKS)


# ── FileUploadConnector tests ─────────────────────────────────────


class TestFileUploadConnector:
    @pytest.fixture
    def connector(self):
        return FileUploadConnector()

    async def test_validate_config_valid(self, connector):
        config = {
            "s3_key": "projects/p1/uploads/file.csv",
            "file_type": "csv",
            "column_mapping": {"patient_id": "MRN", "text_id": "note_id", "text": "note_text", "note_date": "date"},
        }
        errors = await connector.validate_config(config)
        assert errors == []

    async def test_validate_config_missing_s3_key(self, connector):
        config = {"column_mapping": {"patient_id": "MRN", "text": "note"}}
        errors = await connector.validate_config(config)
        assert any("s3_key" in e for e in errors)

    async def test_validate_config_missing_column_mapping(self, connector):
        config = {"s3_key": "test.csv", "column_mapping": {}}
        errors = await connector.validate_config(config)
        assert any("patient_id" in e for e in errors)
        assert any("text_id" in e for e in errors)
        assert any("text" in e for e in errors)
        assert any("note_date" in e for e in errors)

    async def test_validate_config_bad_file_type(self, connector):
        config = {
            "s3_key": "test.xlsx",
            "file_type": "xlsx",
            "column_mapping": {"patient_id": "id", "text": "t"},
        }
        errors = await connector.validate_config(config)
        assert any("xlsx" in e for e in errors)

    async def test_preview_csv(self, connector):
        csv_data = b"MRN,note_text,date\nP001,Note one,2024-01-01\nP002,Note two,2024-01-02"
        config = {
            "s3_key": "test.csv",
            "file_type": "csv",
            "column_mapping": {"patient_id": "MRN", "text": "note_text"},
        }
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            result = await connector.preview(config, limit=1)
        assert isinstance(result, PreviewResult)
        assert result.columns == ["MRN", "note_text", "date"]
        assert len(result.rows) == 1
        assert result.total_available == 2

    async def test_fetch_csv_batching(self, connector):
        csv_data = b"patient_id,text\nP001,Note1\nP002,Note2\nP003,Note3"
        config = {
            "s3_key": "test.csv",
            "file_type": "csv",
            "column_mapping": {"patient_id": "patient_id", "text": "text"},
        }
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            result = await connector.fetch(config, batch_size=2, offset=0)
        assert len(result.rows) == 2
        assert result.has_more is True

        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            result = await connector.fetch(config, batch_size=2, offset=2)
        assert len(result.rows) == 1
        assert result.has_more is False

    async def test_fetch_json_array(self, connector):
        data = [
            {"patient_id": "P001", "text": "Note one"},
            {"patient_id": "P002", "text": "Note two"},
        ]
        json_data = json.dumps(data).encode()
        config = {
            "s3_key": "test.json",
            "file_type": "json",
            "column_mapping": {"patient_id": "patient_id", "text": "text"},
        }
        with patch("app.connectors.file_upload.download_file", return_value=json_data):
            result = await connector.fetch(config)
        assert len(result.rows) == 2

    async def test_fetch_json_records_key(self, connector):
        data = {"records": [{"patient_id": "P001", "text": "Note"}]}
        json_data = json.dumps(data).encode()
        config = {
            "s3_key": "test.json",
            "file_type": "json",
            "column_mapping": {"patient_id": "patient_id", "text": "text"},
        }
        with patch("app.connectors.file_upload.download_file", return_value=json_data):
            result = await connector.fetch(config)
        assert len(result.rows) == 1

    def test_required_columns(self, connector):
        cols = connector.required_columns()
        assert "patient_id" in cols
        assert "text_id" in cols
        assert "text" in cols
        assert "note_date" in cols
