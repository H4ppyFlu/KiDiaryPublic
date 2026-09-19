from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


class Health(BaseModel):
    database_time: datetime
    database_version: str


@router.get("/health")
def read_health(session: Annotated[Session, Depends(get_session)]) -> Health:
    """Prove the round trip: the browser reached the API, which reached Postgres.

    Only the database server can answer either of these, so a 200 here means
    every hop worked.
    """
    now, version = session.execute(text("select now(), version()")).one()
    return Health(
        database_time=now,
        # version() is a long banner; "PostgreSQL 17.5" is the readable part.
        database_version=" ".join(version.split()[:2]),
    )
