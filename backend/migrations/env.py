"""Runs migrations against the database the application is configured for.

The URL comes from `Settings`, or from `config.attributes` when the API bootstraps
itself against a database it was handed — which is how the tests migrate their own
`_test` database.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings
from app.models import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    url: str | None = config.attributes.get("database_url")
    return url or Settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
