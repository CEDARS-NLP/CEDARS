"""Alembic environment for global identity and project registry tables."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.auth.models import User  # noqa: E402, F401
from app.common.model_registry import global_metadata  # noqa: E402
from app.projects.models import Project, ProjectMember  # noqa: E402, F401

target_metadata = global_metadata


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
        version_table="global_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            version_table="global_alembic_version",
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
            version_table="global_alembic_version",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
