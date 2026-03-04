"""Tests for Databricks export module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.export.databricks import ExportType, SCHEMAS, export_to_databricks


class TestExportType:
    """Tests for ExportType enum."""

    def test_annotations_value(self):
        assert ExportType.ANNOTATIONS.value == "annotations"

    def test_predictions_value(self):
        assert ExportType.PREDICTIONS.value == "predictions"

    def test_evaluation_value(self):
        assert ExportType.EVALUATION.value == "evaluation"

    def test_all_types_have_schemas(self):
        for et in ExportType:
            assert et in SCHEMAS, f"Missing schema for {et}"


class TestSchemas:
    """Tests for export schemas."""

    def test_annotations_schema_columns(self):
        cols = [name for name, _ in SCHEMAS[ExportType.ANNOTATIONS]]
        assert "patient_id" in cols
        assert "sentence_text" in cols
        assert "review_status" in cols
        assert "reviewer" in cols

    def test_predictions_schema_columns(self):
        cols = [name for name, _ in SCHEMAS[ExportType.PREDICTIONS]]
        assert "patient_id" in cols
        assert "score" in cols
        assert "label" in cols
        assert "reasoning" in cols

    def test_evaluation_schema_columns(self):
        cols = [name for name, _ in SCHEMAS[ExportType.EVALUATION]]
        assert "session_name" in cols
        assert "predicted_label" in cols
        assert "human_judgment" in cols


class TestExportToDatabricks:
    """Tests for export_to_databricks function."""

    @pytest.mark.asyncio
    async def test_data_source_not_found(self):
        """Should raise ValueError when data source doesn't exist."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        with pytest.raises(ValueError, match="Data source not found"):
            await export_to_databricks(
                session=session,
                project_id="proj-1",
                data_source_id="ds-1",
                target_table="output_table",
                export_type=ExportType.ANNOTATIONS,
            )

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero(self):
        """Should return 0 when there are no rows to export."""
        session = AsyncMock()

        # First call: DataSource lookup
        ds_mock = MagicMock()
        ds_mock.config = {
            "host": "test.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc",
            "token": "tok",
            "schema": "default",
        }
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ds_mock
        session.execute.return_value = result_mock

        with patch(
            "app.export.databricks._fetch_export_rows", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = []
            count = await export_to_databricks(
                session=session,
                project_id="proj-1",
                data_source_id="ds-1",
                target_table="output_table",
                export_type=ExportType.ANNOTATIONS,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_exports_rows_to_databricks(self):
        """Should create table and insert rows."""
        session = AsyncMock()

        ds_mock = MagicMock()
        ds_mock.config = {
            "host": "test.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc",
            "token": "tok",
            "catalog": "main",
            "schema": "clinical",
        }
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ds_mock
        session.execute.return_value = result_mock

        fake_rows = [
            ("P1", "T1", "sentence", "confirmed", "2025-01-01", "dr", "2025-01-02"),
            ("P2", "T2", "sentence2", "rejected", None, "dr2", None),
        ]

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch(
                "app.export.databricks._fetch_export_rows", new_callable=AsyncMock
            ) as mock_fetch,
            patch("app.export.databricks.connect_databricks", return_value=mock_conn),
        ):
            mock_fetch.return_value = fake_rows
            count = await export_to_databricks(
                session=session,
                project_id="proj-1",
                data_source_id="ds-1",
                target_table="results",
                export_type=ExportType.ANNOTATIONS,
            )

        assert count == 2
        # CREATE TABLE + 2 INSERT calls
        assert mock_cursor.execute.call_count == 3
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()
