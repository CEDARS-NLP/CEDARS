"""Alembic environment configuration for async SQLAlchemy."""

import os
import subprocess
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings

# Alembic Config object
config = context.config

# Set up Python logging from .ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import the independent metadata registries. Model imports below register
# tables before Alembic receives either target.
from app.annotations.models import Annotation, AnnotationPrediction  # noqa: E402, F401
from app.annotations.review_jobs import PatientReviewJob  # noqa: E402, F401
from app.audit.models import AuditEntry  # noqa: E402, F401

# Import all models so their tables are registered in SQLModel.metadata
from app.auth.models import User  # noqa: E402, F401
from app.common.model_registry import global_metadata, project_metadata  # noqa: E402
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
from app.projects.models import Project, ProjectMember  # noqa: E402, F401

target_metadata = [global_metadata, project_metadata]


def get_sync_url() -> str:
    """Convert the async database URL to a sync one for Alembic migrations.

    Alembic runs migrations synchronously, so we swap asyncpg for psycopg2.
    """
    url = config.get_main_option("sqlalchemy.url") or settings.database_url
    return url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL so that calls to
    context.execute() emit SQL to the script output.
    """
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates a sync engine and runs migrations against a live database.
    """
    if context.get_x_argument(as_dictionary=True).get("legacy") != "true":
        if context.get_revision_argument() != context.get_head_revision():
            raise RuntimeError(
                "Use alembic upgrade head for all databases; use global-alembic.ini "
                "for global schema inspection and revision authoring"
            )
        environment = dict(os.environ)
        environment["CEDARS_DATABASE_URL"] = (
            config.get_main_option("sqlalchemy.url") or settings.database_url
        )
        subprocess.run(
            [sys.executable, "-m", "app.common.migrations"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            check=True,
        )
        return

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
