"""Alembic environment configuration for async SQLAlchemy."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.config import settings

# Alembic Config object
config = context.config

# Set up Python logging from .ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import SQLModel so that all model metadata is registered
from sqlmodel import SQLModel  # noqa: E402

target_metadata = SQLModel.metadata


def get_sync_url() -> str:
    """Convert the async database URL to a sync one for Alembic migrations.

    Alembic runs migrations synchronously, so we swap asyncpg for psycopg2.
    """
    url = settings.database_url
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
