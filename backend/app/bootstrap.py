"""Bring a database up to date and make it usable: migrate, then seed.

Run as `python -m app.bootstrap` before the API starts. It is idempotent, so it runs
on every start rather than only on a fresh Pi, which is what makes "the Prompt bank is
seeded on first run" hold after a rebuild too.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import Settings
from app.db import create_session_factory
from app.seed import seed

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def migrate(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    # Passed as an attribute rather than a main option: a password may contain the
    # `%` that ConfigParser would try to interpolate.
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def migrate_and_seed(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    migrate(settings.database_url)
    session_factory = create_session_factory(settings.database_url)
    with session_factory() as session:
        seed(session, settings)


if __name__ == "__main__":
    # Runs before uvicorn, so it brings its own logging: what a migration did, and any
    # disagreement between the database and configuration, are worth seeing in
    # `docker compose logs`.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    migrate_and_seed()
