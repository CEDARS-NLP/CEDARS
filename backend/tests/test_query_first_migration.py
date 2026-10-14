"""Exercise one additive revision against a model-derived predecessor on scratch SQLite.

This deliberately does not replay the PostgreSQL-specific historical migration chain.
Only this revision's columns, constraints, indexes, and tables are stripped from
current metadata; the predecessor's partial active-query index remains intact.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from app.annotations.models import Annotation
from app.evaluation.models import (
    EvaluationAttempt,
    EvaluationSession,
    LLMPromptRevision,
    PatientResult,
    SearchMatch,
)
from app.nlp.models import SearchQuery
from app.pipeline.models import PipelineRun

BACKEND = Path(__file__).resolve().parents[1]
ADDED_COLUMNS = {
    "evaluation_sessions_v2": {"workflow_version"},
    "search_queries": {"evaluation_session_id", "revision", "syntax_version", "source_queries"},
    "search_matches": {"attempt_id", "query_id"},
    "patient_results": {"attempt_id", "input_snapshot"},
    "pipeline_runs": {"attempt_id", "evaluation_session_id"},
    "annotations": {"attempt_id", "evaluation_session_id"},
}
NEW_TABLES = {"llm_prompt_revisions", "evaluation_attempts"}
MODELS = (
    EvaluationSession,
    SearchQuery,
    LLMPromptRevision,
    EvaluationAttempt,
    SearchMatch,
    PatientResult,
    PipelineRun,
    Annotation,
)


def _predecessor_metadata():
    metadata = sa.MetaData()

    def clone(name):
        if name in metadata.tables:
            return
        assert name not in NEW_TABLES
        source = SQLModel.metadata.tables[name]
        omitted = ADDED_COLUMNS.get(name, set())
        columns = [column for column in source.columns if column.name not in omitted]
        for column in columns:
            for foreign_key in column.foreign_keys:
                target = foreign_key.target_fullname.split(".")[0]
                if target != name:
                    clone(target)
        table = sa.Table(
            name,
            metadata,
            *[
                sa.Column(
                    column.name,
                    column.type,
                    *[
                        sa.ForeignKey(
                            key.target_fullname, ondelete=key.ondelete, onupdate=key.onupdate
                        )
                        for key in column.foreign_keys
                    ],
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    default=column.default,
                    server_default=column.server_default,
                    autoincrement=column.autoincrement,
                )
                for column in columns
            ],
        )
        for constraint in source.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                names = [column.name for column in constraint.columns]
                if not omitted.intersection(names):
                    table.append_constraint(sa.UniqueConstraint(*names, name=constraint.name))
        for index in source.indexes:
            names = [column.name for column in index.columns]
            if not omitted.intersection(names):
                sa.Index(
                    index.name,
                    *(table.c[name] for name in names),
                    unique=index.unique,
                    **dict(index.dialect_kwargs),
                )

    for name in ADDED_COLUMNS:
        clone(name)
    return metadata


@pytest.fixture
def scratch():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        metadata = _predecessor_metadata()
        metadata.create_all(connection)
        connection.commit()
        yield connection, metadata
    engine.dispose()


@pytest.fixture
def migration():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("7c91d2e8f640")
    assert revision.down_revision == "f4a9c21e7b83"
    assert scripts.get_revision(revision.down_revision) is not None
    return revision.module


def _migrate(connection, migration, direction):
    """Suspend SQLite FK enforcement only for Alembic's copy/drop/rename batches.

    SQLite cannot drop a referenced table with enforcement enabled. Validate
    every FK before committing, then restore enforcement for all data checks.
    """
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql("BEGIN")
    try:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            getattr(migration, direction)()
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        connection.commit()
    finally:
        connection.rollback()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    connection.commit()


def _schema(connection, name):
    inspector = sa.inspect(connection)
    return {
        "columns": {
            column["name"]: (
                str(column["type"].compile(dialect=connection.dialect)),
                column["nullable"],
                column["primary_key"],
            )
            for column in inspector.get_columns(name)
        },
        "pk": tuple(inspector.get_pk_constraint(name)["constrained_columns"]),
        "fks": {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
            )
            for key in inspector.get_foreign_keys(name)
        },
        "unique": {
            (key["name"], tuple(key["column_names"]))
            for key in inspector.get_unique_constraints(name)
        },
        "indexes": {
            (
                index["name"],
                tuple(index["column_names"]),
                bool(index["unique"]),
                str(index.get("dialect_options", {}).get("sqlite_where", "")),
            )
            for index in inspector.get_indexes(name)
        },
    }


def _seed_legacy(connection, metadata):
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    rows = {
        "users": {
            "id": "user",
            "email": "migration@example.com",
            "name": "Test",
            "password_hash": "unused",
        },
        "projects": {"id": "project", "name": "Scratch", "owner_id": "user"},
        "patients": {"id": "patient", "project_id": "project", "patient_id_ext": "synthetic"},
        "notes": {
            "id": "note",
            "project_id": "project",
            "patient_id": "patient",
            "text_id": "text",
            "note_date": now,
            "text": "Synthetic DVT.",
        },
        "evaluation_sessions_v2": {
            "id": "session",
            "project_id": "project",
            "created_by": "user",
            "event_name": "Legacy event",
        },
        "search_queries": {
            "id": "query",
            "project_id": "project",
            "query": "DVT",
            "is_active": True,
        },
        "event_configs": {
            "id": "config",
            "project_id": "project",
            "name": "Legacy",
            "description": "Synthetic",
            "include_criteria": "DVT",
            "llm_provider": "test",
            "llm_model": "test",
        },
        "pipeline_runs": {
            "id": "run",
            "project_id": "project",
            "event_config_id": "config",
            "run_type": "full",
            "status": "queued",
        },
        "search_matches": {
            "id": 1,
            "session_id": "session",
            "patient_id": "patient",
            "note_id": "note",
        },
        "patient_results": {
            "id": 1,
            "session_id": "session",
            "patient_id": "patient",
            "pipeline_run_id": "run",
            "finding_label": "present",
        },
        "annotations": {
            "id": "annotation",
            "project_id": "project",
            "patient_id": "patient",
            "note_id": "note",
            "pipeline_run_id": "run",
            "sentence_text": "Synthetic DVT.",
            "sentence_start": 0,
            "sentence_end": 14,
        },
    }
    for name, values in rows.items():
        values.update(
            {
                column.name: now
                for column in metadata.tables[name].columns
                if not column.nullable
                and isinstance(column.type, sa.DateTime)
                and column.name not in values
            }
        )
        connection.execute(metadata.tables[name].insert().values(**values))
    connection.commit()
    return {
        name: connection.execute(sa.select(table)).mappings().all()
        for name, table in metadata.tables.items()
    }


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__tablename__)
def test_upgrade_matches_model_schema(scratch, migration, model):
    connection, predecessor = scratch
    _migrate(connection, migration, "upgrade")
    expected = sa.MetaData()
    for name in predecessor.tables.keys() | NEW_TABLES:
        SQLModel.metadata.tables[name].to_metadata(expected)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as model_connection:
            expected.create_all(model_connection)
            assert _schema(connection, model.__tablename__) == _schema(
                model_connection, model.__tablename__
            )
    finally:
        engine.dispose()


def test_upgrade_preserves_legacy_data_defaults_and_active_index(scratch, migration):
    connection, metadata = scratch
    original = _seed_legacy(connection, metadata)
    active_index = _schema(connection, "search_queries")["indexes"]
    _migrate(connection, migration, "upgrade")
    for name, rows in original.items():
        assert connection.execute(sa.select(metadata.tables[name])).mappings().all() == rows
    assert active_index <= _schema(connection, "search_queries")["indexes"]
    assert (
        connection.exec_driver_sql(
            "SELECT workflow_version FROM evaluation_sessions_v2"
        ).scalar_one()
        == 1
    )
    assert connection.exec_driver_sql(
        "SELECT evaluation_session_id, revision, syntax_version, source_queries, is_active FROM search_queries"
    ).one() == (None, None, 1, "[]", 1)
    for name, columns in ADDED_COLUMNS.items():
        reflected = {column["name"]: column for column in sa.inspect(connection).get_columns(name)}
        for column in columns - {"workflow_version", "syntax_version", "source_queries"}:
            assert reflected[column]["nullable"], (name, column)
            assert (
                connection.exec_driver_sql(f'SELECT "{column}" FROM "{name}"').scalar_one() is None
            )
    connection.exec_driver_sql(
        "INSERT INTO evaluation_sessions_v2 (id, project_id, status, sample_size, created_by) VALUES ('new-legacy', 'project', 'draft', 1, 'user')"
    )
    assert (
        connection.exec_driver_sql(
            "SELECT workflow_version FROM evaluation_sessions_v2 WHERE id='new-legacy'"
        ).scalar_one()
        == 1
    )
    query = metadata.tables["search_queries"]
    with pytest.raises(IntegrityError):
        connection.execute(
            query.insert().values(
                id="second-active",
                project_id="project",
                query="PE",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
    connection.execute(
        query.insert().values(
            id="inactive",
            project_id="project",
            query="PE",
            is_active=False,
            created_at=datetime.now(timezone.utc),
        )
    )
    connection.execute(
        query.insert().values(
            id="deleted-active",
            project_id="project",
            query="PE",
            is_active=True,
            deleted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )


@pytest.mark.parametrize("populated", [False, True], ids=["empty", "legacy-linked"])
def test_downgrade_upgrade_round_trip_preserves_predecessor(scratch, migration, populated):
    connection, metadata = scratch
    original = _seed_legacy(connection, metadata) if populated else {}
    predecessor = {name: _schema(connection, name) for name in metadata.tables}
    for _ in range(2):
        _migrate(connection, migration, "upgrade")
        upgraded = {name: _schema(connection, name) for name in ADDED_COLUMNS.keys() | NEW_TABLES}
        _migrate(connection, migration, "downgrade")
        assert set(sa.inspect(connection).get_table_names()) == set(metadata.tables)
        assert {name: _schema(connection, name) for name in metadata.tables} == predecessor
        for name, rows in original.items():
            assert connection.execute(sa.select(metadata.tables[name])).mappings().all() == rows
        _migrate(connection, migration, "upgrade")
        assert {name: _schema(connection, name) for name in upgraded} == upgraded
        _migrate(connection, migration, "downgrade")


def test_new_lineage_foreign_keys_and_unique_constraints_are_enforced(scratch, migration):
    connection, metadata = scratch
    _migrate(connection, migration, "upgrade")
    _seed_legacy(connection, metadata)
    query = SearchQuery.__table__
    query_values = dict(
        project_id="project",
        query="DVT",
        is_active=False,
        evaluation_session_id="session",
        revision=1,
        created_at=datetime.now(timezone.utc),
    )
    connection.execute(query.insert().values(id="revision", **query_values))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        connection.execute(query.insert().values(id="duplicate", **query_values))
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        connection.execute(
            query.insert().values(
                **(
                    query_values
                    | {"id": "bad-query", "revision": 2, "evaluation_session_id": "missing"}
                )
            )
        )
    prompt = LLMPromptRevision.__table__
    prompt_values = dict(
        id="prompt",
        session_id="session",
        project_id="project",
        revision=1,
        event_name="Synthetic",
        event_description="Synthetic event",
        include_criteria="DVT",
        exclude_criteria="",
        llm_provider="test",
        llm_model="test",
        template="Synthetic template",
        template_version=1,
        generation_settings={},
        created_by="user",
    )
    connection.execute(prompt.insert().values(**prompt_values))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        connection.execute(prompt.insert().values(**(prompt_values | {"id": "duplicate-prompt"})))
    for column in ("session_id", "project_id", "created_by"):
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                prompt.insert().values(
                    **(prompt_values | {"id": "bad-prompt", "revision": 2, column: "missing"})
                )
            )
    attempt = EvaluationAttempt.__table__
    values = dict(
        id="attempt",
        session_id="session",
        query_id="revision",
        sequence=1,
        mode="search",
        scope="sample",
        created_by="user",
        sample_patient_ids=[],
        metrics={},
    )
    connection.execute(attempt.insert().values(**values))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        connection.execute(attempt.insert().values(**(values | {"id": "duplicate"})))
    for column in (
        "session_id",
        "query_id",
        "prompt_revision_id",
        "source_attempt_id",
        "created_by",
    ):
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                attempt.insert().values(
                    **(values | {"id": "bad", "sequence": 2, column: "missing"})
                )
            )
    for model in (SearchMatch, PatientResult, PipelineRun, Annotation):
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(model.__table__.update().values(attempt_id="missing"))
    for model in (PipelineRun, Annotation):
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(model.__table__.update().values(evaluation_session_id="missing"))
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        connection.execute(SearchMatch.__table__.update().values(query_id="missing"))
    connection.execute(
        attempt.insert().values(
            **(
                values
                | {
                    "id": "other-attempt",
                    "sequence": 2,
                    "prompt_revision_id": "prompt",
                    "source_attempt_id": "attempt",
                }
            )
        )
    )
    for model in (PatientResult, Annotation):
        table = model.__table__
        connection.execute(table.update().values(attempt_id="attempt"))
        row = dict(connection.execute(sa.select(table)).mappings().one())
        row["id"] = 2 if model is PatientResult else "duplicate-annotation"
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(table.insert().values(**row))
        connection.execute(table.insert().values(**(row | {"attempt_id": "other-attempt"})))
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_populated_sqlite_batch_requires_fk_suspension(scratch, migration):
    connection, metadata = scratch
    _seed_legacy(connection, metadata)
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    context = MigrationContext.configure(connection)
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed") as failure:
        with Operations.context(context):
            migration.upgrade()
    assert "DROP TABLE pipeline_runs" in failure.value.statement
