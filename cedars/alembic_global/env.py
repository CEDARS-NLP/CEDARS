'''
alembic_global/env.py

Alembic environment for the GLOBAL application database (Users, Projects,
UserProjectRelation). Run with: `alembic -c alembic_global.ini upgrade head`
'''
from logging.config import fileConfig

from alembic import context

from cedars.app.database import get_global_engine
from cedars.app.database.global_app_tables import GlobalBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = GlobalBase.metadata


def run_migrations_offline() -> None:
    '''Emit SQL to stdout instead of executing against a live connection.'''
    context.configure(
        url=str(get_global_engine().url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    '''Run migrations against the live global database engine.'''
    connectable = get_global_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
