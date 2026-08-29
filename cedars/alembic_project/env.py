'''
alembic_project/env.py

Alembic environment for a PER-PROJECT database (Patients, Notes, Annotations,
...). Since every project has its own database, the target must be selected at
invocation time via `-x project_id=<id>`, e.g.:

    alembic -c alembic_project.ini upgrade head -x project_id=abc123

Run once per project when adding a new migration (see
cedars/app/database/init_db.py for the programmatic equivalent used when a
project is first created).
'''
from logging.config import fileConfig

from alembic import context

from cedars.app.database import get_project_engine
from cedars.app.database.project_table_creation import ProjectBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ProjectBase.metadata


def _project_id() -> str:
    project_id = context.get_x_argument(as_dictionary=True).get("project_id")
    if not project_id:
        raise RuntimeError(
            "alembic_project requires -x project_id=<id> (each project has its own database).")
    return project_id


def run_migrations_offline() -> None:
    '''Emit SQL to stdout instead of executing against a live connection.'''
    context.configure(
        url=str(get_project_engine(_project_id()).url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    '''Run migrations against the live engine for the selected project.'''
    connectable = get_project_engine(_project_id())

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
