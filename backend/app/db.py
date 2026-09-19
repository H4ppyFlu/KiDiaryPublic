from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, from the factory the app was built with."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
