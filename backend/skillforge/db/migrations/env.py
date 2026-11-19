"""Alembic environment. Migrations are run from code (`Database.migrate`) on a connection that is passed in."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from skillforge.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:  # run by the alembic command line instead
        engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connection)


def _run(connection) -> None:
    # render_as_batch: SQLite cannot alter a table in place, so later migrations are written as batch operations.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
