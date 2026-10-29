"""Alembic environment for project-local databases."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import models so every project-local table is registered before autogeneration.
from app.annotations.models import Annotation, AnnotationPrediction  # noqa: E402, F401
from app.annotations.review_jobs import PatientReviewJob  # noqa: E402, F401
from app.audit.models import AuditEntry  # noqa: E402, F401
from app.common.model_registry import project_metadata  # noqa: E402
from app.connectors.models import DataSource, Note, Patient  # noqa: E402, F401
from app.evaluation.models import (  # noqa: E402, F401
    EvaluationSession,
    EvaluationSessionQuerySection,
    PatientResult,
    SearchMatch,
)
from app.jobs.models import BackgroundJob  # noqa: E402, F401
from app.llm.usage import LlmUsage  # noqa: E402, F401
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: E402, F401
from app.pipeline.models import EventConfig, Evidence, PatientTask, PipelineRun  # noqa: E402, F401
from app.predictors.models import PredictorConfig  # noqa: E402, F401
from app.production.models import (  # noqa: E402, F401
    NotePrediction,
    ProductionResult,
    ProductionRun,
    ProductionState,
)
from app.projects.models import ProjectUser  # noqa: E402, F401

target_metadata = project_metadata


def _include_name(name: str | None, object_type: str, parent_names: dict[str, str]) -> bool:
    return object_type != "table" or name != "global_alembic_version"


def _sync_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername.endswith("+asyncpg"):
        parsed = parsed.set(drivername="postgresql+psycopg2")
    elif parsed.drivername.endswith("+aiosqlite"):
        parsed = parsed.set(drivername="sqlite")
    return parsed.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(config.get_main_option("sqlalchemy.url") or settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="project_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            version_table="project_alembic_version",
            include_name=_include_name,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url(
        config.get_main_option("sqlalchemy.url") or settings.database_url
    )
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="project_alembic_version",
            include_name=_include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
