"""Global and per-project Alembic migration entry points."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import JSON, Engine, cast, create_engine, inspect, literal, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.annotations.models import Annotation, AnnotationPrediction  # noqa: F401
from app.annotations.review_jobs import PatientReviewJob  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401
from app.auth.models import User
from app.common.model_registry import global_metadata, project_metadata
from app.config import settings
from app.connectors.models import DataSource, Note, Patient  # noqa: F401
from app.evaluation.models import (  # noqa: F401
    EvaluationSession,
    EvaluationSessionQuerySection,
    PatientResult,
    SearchMatch,
)
from app.jobs.models import BackgroundJob  # noqa: F401
from app.llm.usage import LlmUsage  # noqa: F401
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: F401
from app.pipeline.models import EventConfig, Evidence, PatientTask, PipelineRun  # noqa: F401
from app.predictors.models import PredictorConfig  # noqa: F401
from app.production.models import (  # noqa: F401
    NotePrediction,
    ProductionResult,
    ProductionRun,
    ProductionState,
)
from app.projects.models import Project, ProjectMember, ProjectUser

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_GLOBAL_INI = _BACKEND_DIR / "global-alembic.ini"
_PROJECT_INI = _BACKEND_DIR / "project-alembic.ini"
_GLOBAL_BASELINE = "g0001_global_baseline"
_GLOBAL_LOCK_ID = 1128613197
_PROJECT_LOCK_ID = 1128613198
_ALEMBIC_LOCK = RLock()


def _sync_url(database_url: str) -> URL:
    url = make_url(database_url)
    if url.drivername.startswith("postgresql"):
        return url.set(drivername="postgresql+psycopg2")
    if url.drivername == "sqlite+aiosqlite":
        return url.set(drivername="sqlite")
    return url


def _config(ini_path: Path, connection) -> Config:
    config = Config(str(ini_path))
    config.attributes["connection"] = connection
    return config


@contextmanager
def _migration_connection(database_url: str, lock_id: int) -> Iterator[tuple[Engine, Any]]:
    engine = create_engine(_sync_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            locked = connection.dialect.name == "postgresql"
            if locked:
                connection.exec_driver_sql(f"SELECT pg_advisory_lock({_GLOBAL_LOCK_ID}, {lock_id})")
                connection.commit()
            try:
                yield engine, connection
            except BaseException:
                connection.rollback()
                raise
            finally:
                if locked:
                    if connection.in_transaction():
                        connection.commit()
                    connection.exec_driver_sql(
                        f"SELECT pg_advisory_unlock({_GLOBAL_LOCK_ID}, {lock_id})"
                    )
                    connection.commit()
    finally:
        engine.dispose()


def _compare_server_default(
    context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
) -> bool | None:
    if (
        context.dialect.name == "postgresql"
        and isinstance(metadata_column.type, JSON)
        and inspected_default is not None
        and rendered_metadata_default is not None
    ):
        default_expression = (
            literal(metadata_default.arg)
            if isinstance(metadata_default.arg, str)
            else text(rendered_metadata_default)
        )
        return not context.connection.scalar(
            select(cast(text(inspected_default), JSONB) == cast(default_expression, JSONB))
        )
    return None


def _metadata_differences(connection, metadata) -> list[tuple[Any, ...]]:
    table_names = set(metadata.tables)

    def include_name(name: str | None, object_type: str, parent_names: dict[str, str]) -> bool:
        if object_type == "table":
            return name in table_names
        return True

    migration_context = MigrationContext.configure(
        connection,
        opts={
            "target_metadata": metadata,
            "include_name": include_name,
            "compare_type": True,
            "compare_server_default": (
                _compare_server_default if connection.dialect.name == "postgresql" else False
            ),
        },
    )
    return compare_metadata(migration_context, metadata)


def _adopt_existing_schema(
    connection,
    metadata,
    version_table: str,
    baseline_revision: str,
    config: Config,
) -> bool:
    """Stamp a schema only after all expected tables and metadata compare cleanly."""
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(metadata.tables)
    present = expected_tables.intersection(existing_tables)
    if not present:
        return False
    if present != expected_tables:
        missing = sorted(expected_tables - present)
        raise RuntimeError(f"Refusing baseline adoption; database is missing tables: {missing}")
    differences = _metadata_differences(connection, metadata)
    if differences:
        raise RuntimeError(
            f"Refusing baseline adoption; schema differs from frozen baseline: {differences[:8]}"
        )
    config.attributes["version_table"] = version_table
    command.stamp(config, baseline_revision)
    return True


def _upgrade_database(
    database_url: str,
    ini_path: Path,
    lock_id: int,
    metadata,
    version_table: str,
    baseline_revision: str,
) -> str:
    with _ALEMBIC_LOCK, _migration_connection(database_url, lock_id) as (_, connection):
        config = _config(ini_path, connection)
        tables = set(inspect(connection).get_table_names())
        if connection.in_transaction():
            connection.commit()
        if version_table not in tables:
            adopted = _adopt_existing_schema(
                connection, metadata, version_table, baseline_revision, config
            )
            if not adopted:
                if connection.in_transaction():
                    connection.commit()
                command.upgrade(config, "head")
                return _current_head(config)
            if connection.in_transaction():
                connection.commit()
        command.upgrade(config, "head")
        return _current_head(config)


def _current_head(config: Config) -> str:
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError(f"No migration head configured for {config.config_file_name}")
    return head


def get_project_migration_head() -> str:
    """Return the expected tenant schema revision used for Project records."""
    return _current_head(Config(str(_PROJECT_INI)))


def migrate_project_database(database_url: str) -> str:
    """Upgrade one project database and return its current project migration head.

    This function is synchronous so async provisioning code should call it via
    ``asyncio.to_thread``. It never uses the historical combined migration chain.
    """
    return _upgrade_database(
        database_url,
        _PROJECT_INI,
        _PROJECT_LOCK_ID,
        project_metadata,
        "project_alembic_version",
        "p0001_project_baseline",
    )


def migrate_global_database(database_url: str) -> str:
    """Upgrade global identity and project registry tables, preserving legacy history."""
    return _upgrade_database(
        database_url,
        _GLOBAL_INI,
        _GLOBAL_LOCK_ID,
        global_metadata,
        "global_alembic_version",
        _GLOBAL_BASELINE,
    )


def _resolve_database_secret(secret_ref: str) -> str:
    from app.common.project_database import _get_secret

    return _get_secret(secret_ref)


def _backfill_project_users(
    global_engine: Engine,
    project_database_url: str,
    project: Project,
) -> None:
    with Session(global_engine) as global_session:
        membership_rows = global_session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project.id)
        ).all()

    if not membership_rows:
        return

    rows = [
        {
            "global_user_id": member.user_id,
            "project_id": project.id,
            "email": user.email,
            "name": user.name,
            "role": member.role.value,
            "is_investigator": member.user_id == project.owner_id,
            "is_active": member.is_active,
            "added_by_kind": member.added_by_kind,
            "added_by_user_id": None,
            "membership_revision": member.membership_revision,
            "created_at": member.created_at,
            "revoked_at": member.revoked_at,
        }
        for member, user in membership_rows
    ]
    member_ids = {row["global_user_id"] for row in rows}

    with _migration_connection(project_database_url, _PROJECT_LOCK_ID) as (_, connection):
        with Session(bind=connection) as tenant_session:
            existing = {
                user.global_user_id: user
                for user in tenant_session.scalars(select(ProjectUser)).all()
            }
            for row in rows:
                local_user = existing.get(row["global_user_id"])
                if local_user is None:
                    local_user = ProjectUser(**row)
                    tenant_session.add(local_user)
                    existing[row["global_user_id"]] = local_user
                else:
                    for field, value in row.items():
                        if field != "global_user_id":
                            setattr(local_user, field, value)
            tenant_session.flush()
            for row in rows:
                user = existing[row["global_user_id"]]
                adder_id = next(
                    member.added_by_user_id
                    for member, source_user in membership_rows
                    if source_user.id == row["global_user_id"]
                )
                user.added_by_user_id = adder_id if adder_id in member_ids else None
            tenant_session.commit()


def migrate_all_databases(global_database_url: str | None = None) -> None:
    """Upgrade global first, then every registered project database serially."""
    global_database_url = global_database_url or settings.database_url
    migrate_global_database(global_database_url)
    global_engine = create_engine(_sync_url(global_database_url), pool_pre_ping=True)
    try:
        with Session(global_engine) as session:
            projects = list(session.scalars(select(Project).order_by(Project.id)).all())
        missing_refs = [project.id for project in projects if not project.database_secret_ref]
        if missing_refs:
            raise RuntimeError(
                "Project database migration preflight failed; missing database_secret_ref for: "
                + ", ".join(missing_refs)
            )

        failures: list[str] = []
        expected_head = get_project_migration_head()
        for project in projects:
            try:
                project_database_url = _resolve_database_secret(project.database_secret_ref)
                migrated_head = migrate_project_database(project_database_url)
                if migrated_head != expected_head:
                    raise RuntimeError(
                        f"Tenant head {migrated_head} does not match expected {expected_head}"
                    )
                _backfill_project_users(global_engine, project_database_url, project)
                with Session(global_engine) as session:
                    current_project = session.get(Project, project.id)
                    if current_project is None:
                        raise RuntimeError("Project disappeared while migration was running")
                    current_project.database_schema_version = migrated_head
                    session.commit()
                logger.info("Migrated project database %s to %s", project.id, migrated_head)
            except Exception:
                logger.error("Project database migration failed for project %s", project.id)
                failures.append(project.id)

        if failures:
            raise RuntimeError("Project database migration failed for: " + ", ".join(failures))
    finally:
        global_engine.dispose()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        migrate_all_databases()
    except Exception:
        logger.error("Database migration runner failed; application startup must stop")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
