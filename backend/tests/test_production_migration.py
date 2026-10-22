from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.production.models import ProductionResult

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "c1d2e3f4a5b6"
PRODUCTION_REVISION = "d4e5f6a7b8c9"


def _alembic_config(database_url: str, output_buffer=None) -> Config:
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _create_pre_revision_schema(engine) -> None:
    metadata = MetaData()
    Table("users", metadata, Column("id", String, primary_key=True), Column("email", String),
          Column("name", String), Column("password_hash", String), Column("role", String),
          Column("is_active", Boolean), Column("created_at", DateTime))
    Table("projects", metadata, Column("id", String, primary_key=True), Column("name", String),
          Column("description", Text), Column("owner_id", String, ForeignKey("users.id")),
          Column("settings", JSON), Column("created_at", DateTime))
    Table(
        "patients", metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, ForeignKey("projects.id"), nullable=False),
        Column("patient_id_ext", String, nullable=False),
        Column("status", String, nullable=False),
        Column("review_source", String),
        Column("review_reason", String),
        Column("reviewed_by", String, ForeignKey("users.id")),
        Column("reviewed_at", DateTime),
        Column("locked_by", String, ForeignKey("users.id")),
        Column("locked_at", DateTime),
        Column("metadata", JSON, nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        Column("deleted_at", DateTime),
        UniqueConstraint("project_id", "patient_id_ext", name="uq_patient_ext_id"),
    )
    Table(
        "notes", metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, ForeignKey("projects.id"), nullable=False),
        Column("patient_id", String, ForeignKey("patients.id"), nullable=False),
        Column("text_id", String, nullable=False),
        Column("note_date", DateTime, nullable=False),
        Column("text", Text, nullable=False),
        Column("metadata", JSON, nullable=False),
        Column("source_ref", String),
        Column("data_source_id", String),
        Column("created_at", DateTime, nullable=False),
        Column("deleted_at", DateTime),
        UniqueConstraint("project_id", "text_id", name="uq_note_text_id"),
    )
    Table("annotations", metadata, Column("id", String, primary_key=True))
    Table(
        "annotation_predictions", metadata,
        Column("id", String, primary_key=True),
        Column("annotation_id", String, ForeignKey("annotations.id")),
    )
    Table("pipeline_runs", metadata, Column("id", String, primary_key=True))
    Table("patient_tasks", metadata, Column("id", Integer, primary_key=True))
    Table(
        "evaluation_sessions_v2", metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, ForeignKey("projects.id"), nullable=False),
        Column("created_by", String, ForeignKey("users.id"), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    Table(
        "audit_log", metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, ForeignKey("projects.id"), nullable=False),
        Column("patient_id", String, ForeignKey("patients.id")),
        Column("user_id", String, ForeignKey("users.id")),
        Column("action", String, nullable=False),
        Column("detail", JSON, nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)


def _assert_result_columns_match_model(connection) -> None:
    migrated = {column["name"]: column for column in inspect(connection).get_columns("RESULTS")}
    model_columns = ProductionResult.__table__.columns
    assert set(migrated) == set(model_columns.keys())
    for name, model_column in model_columns.items():
        migrated_column = migrated[name]
        assert migrated_column["nullable"] is model_column.nullable, name
        assert migrated_column["type"]._type_affinity is model_column.type._type_affinity, name
        if isinstance(model_column.type, String):
            assert migrated_column["type"].length == model_column.type.length, name
        if connection.dialect.name != "sqlite" and isinstance(model_column.type, DateTime):
            assert migrated_column["type"].timezone == model_column.type.timezone, name
    assert any(
        foreign_key["constrained_columns"] == ["reviewer"]
        and foreign_key["referred_table"] == "users"
        and foreign_key["referred_columns"] == ["id"]
        for foreign_key in inspect(connection).get_foreign_keys("RESULTS")
    )


def test_production_migration_preserves_source_rows_and_enforces_constraints(tmp_path):
    database_path = tmp_path / "migration.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = _alembic_config(database_url)

    engine = create_engine(database_url)
    _create_pre_revision_schema(engine)
    command.stamp(config, PREVIOUS_HEAD)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, name, password_hash, role, is_active, created_at) "
                "VALUES ('user-1', 'migration@example.test', 'Migration', 'unused', "
                "'USER', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, name, description, owner_id, settings, created_at) "
                "VALUES ('project-1', 'Migration', '', 'user-1', '{}', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO patients "
                "(id, project_id, patient_id_ext, status, review_source, review_reason, "
                "reviewed_by, reviewed_at, locked_by, locked_at, metadata, created_at, updated_at) "
                "VALUES ('patient-1', 'project-1', 'external-1', 'REVIEWED', 'manual', "
                "'legacy reason', 'user-1', CURRENT_TIMESTAMP, 'user-1', CURRENT_TIMESTAMP, '{}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO patients "
                "(id, project_id, patient_id_ext, status, metadata, created_at, updated_at, "
                "deleted_at) VALUES ('patient-deleted', 'project-1', 'external-deleted', 'NEW', "
                "'{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO annotations (id) VALUES ('legacy-annotation')"))
        connection.execute(
            text(
                "INSERT INTO annotation_predictions (id, annotation_id) "
                "VALUES ('legacy-prediction', 'legacy-annotation')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO notes "
                "(id, project_id, patient_id, text_id, note_date, text, metadata, created_at) "
                "VALUES ('note-1', 'project-1', 'patient-1', 'external-note-1', "
                "CURRENT_TIMESTAMP, 'source note', '{}', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO evaluation_sessions_v2 "
                "(id, project_id, created_by, created_at, updated_at) "
                "VALUES ('eval-1', 'project-1', 'user-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO audit_log "
                "(id, project_id, patient_id, user_id, action, detail, created_at) "
                "VALUES ('audit-1', 'project-1', 'patient-1', 'user-1', 'PATIENT_LOCKED', "
                "'{}', CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(config, PRODUCTION_REVISION)

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        tables = set(inspect(connection).get_table_names())
        assert {"patients", "notes", "evaluation_sessions_v2", "audit_log"} <= tables
        assert {
            "Annotations",
            "production_runs",
            "production_states",
            "note_predictions",
            "RESULTS",
        } <= tables
        assert "annotations" not in tables
        assert "annotation_predictions" not in tables
        assert connection.execute(
            text("SELECT patient_id_ext FROM notes WHERE id = 'note-1'")
        ).scalar_one() == "external-1"
        assert connection.execute(
            text("SELECT text FROM notes WHERE id = 'note-1'")
        ).scalar_one() == "source note"
        assert connection.execute(
            text("SELECT patient_id_ext FROM patients WHERE id = 'patient-1'")
        ).scalar_one() == "external-1"
        assert connection.execute(
            text("SELECT id FROM evaluation_sessions_v2 WHERE id = 'eval-1'")
        ).scalar_one() == "eval-1"
        assert connection.execute(
            text("SELECT id FROM audit_log WHERE id = 'audit-1'")
        ).scalar_one() == "audit-1"
        _assert_result_columns_match_model(connection)
        assert connection.execute(text('SELECT COUNT(*) FROM "RESULTS"')).scalar_one() == 1
        assert connection.execute(
            text(
                'SELECT patient_uuid, patient_id, processing_status, review_status FROM "RESULTS"'
            )
        ).one() == ("patient-1", "external-1", "queued", "pending")
        patient = connection.execute(
            text(
                "SELECT status, review_source, review_reason, reviewed_by, reviewed_at, "
                "locked_by, locked_at, event_date, event_annotation_id, event_reviewer "
                "FROM patients WHERE id = 'patient-1'"
            )
        ).one()
        assert patient == ("NEW", None, None, None, None, None, None, None, None, None)

        note_fks = inspect(connection).get_foreign_keys("notes")
        assert any(
            fk["constrained_columns"] == ["project_id", "patient_id_ext"]
            and fk["referred_table"] == "patients"
            for fk in note_fks
        )
        annotation_fks = inspect(connection).get_foreign_keys("Annotations")
        assert any(
            fk["constrained_columns"] == ["project_id", "text_id", "patient_id"]
            and fk["referred_table"] == "notes"
            for fk in annotation_fks
        )
        assert any(
            fk["constrained_columns"] == ["project_id", "patient_id_ext", "event_annotation_id"]
            and fk["referred_table"] == "Annotations"
            for fk in inspect(connection).get_foreign_keys("patients")
        )
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

        connection.execute(
            text(
                "INSERT INTO Annotations "
                "(project_id, text_id, patient_id, text_date, sentence, token, isNegated, "
                "note_start_index, note_end_index, sentence_number, sentence_start, "
                "sentence_end, created_at) VALUES ('project-1', 'external-note-1', "
                "'external-1', '2025-04-03', 'No event.', 'event', 1, 3, 8, 0, 0, 9, "
                "CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "UPDATE patients SET event_date = '2025-04-03', event_annotation_id = "
                "(SELECT annotation_id FROM Annotations), event_reviewer = 'user-1' "
                "WHERE id = 'patient-1'"
            )
        )
        connection.commit()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO notes "
                    "(id, project_id, patient_id, text_id, patient_id_ext, note_date, text, "
                    "metadata, created_at) VALUES ('bad-note', 'project-1', 'patient-1', "
                    "'external-note-2', 'wrong-patient', CURRENT_TIMESTAMP, 'bad', '{}', "
                    "CURRENT_TIMESTAMP)"
                )
            )

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO patients "
                    "(id, project_id, patient_id_ext, status, metadata, created_at, updated_at, "
                    "event_date) VALUES ('bad-patient', 'project-1', 'external-2', 'NEW', "
                    "'{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '2025-04-03')"
                )
            )

    engine.dispose()


def test_production_migration_renders_postgresql_sql():
    output = StringIO()
    config = _alembic_config("postgresql+psycopg2://cedars:cedars@localhost/cedars", output)

    command.upgrade(config, f"{PREVIOUS_HEAD}:{PRODUCTION_REVISION}", sql=True)

    sql = output.getvalue()
    assert 'CREATE TABLE "Annotations"' in sql
    assert 'CREATE TABLE note_predictions' in sql
    assert "fk_patient_event_annotation_same_patient" in sql
    assert "fk_note_predictions_note_patient_external" in sql


@pytest.mark.skipif(
    not os.getenv("CEDARS_TEST_POSTGRES_URL"),
    reason="set CEDARS_TEST_POSTGRES_URL to an existing disposable PostgreSQL database",
)
def test_production_migration_matches_model_on_postgresql():
    configured_url = os.environ["CEDARS_TEST_POSTGRES_URL"]
    sync_url = configured_url.replace("+asyncpg", "+psycopg2")
    base_engine = create_engine(sync_url)
    schema = f"migration_test_{uuid4().hex}"
    try:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        isolated_url = make_url(sync_url).update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        engine = create_engine(isolated_url)
        try:
            _create_pre_revision_schema(engine)
            config = _alembic_config(str(isolated_url))
            command.stamp(config, PREVIOUS_HEAD)
            command.upgrade(config, PRODUCTION_REVISION)
            with engine.connect() as connection:
                _assert_result_columns_match_model(connection)
        finally:
            engine.dispose()
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        base_engine.dispose()
