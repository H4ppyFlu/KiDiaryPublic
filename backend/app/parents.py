"""The two Parents, as the app has to name them.

There are exactly two, they are seeded rather than created in the app, and `position`
is the natural key that says so (`models.py`). This module only reads them. It exists
because a device that has just typed the PIN has to be shown two names to choose
between (ADR-0010).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Parent

router = APIRouter()


class ParentProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    name: str


def the_parent(session: Session, parent_id: int | None) -> Parent | None:
    """The Parent a device claims to be, or nobody.

    Nobody covers both a device that has not said yet and a cookie that outlived the
    row it names — a Pi restored from a backup taken before the seed. Neither is an
    error here; both are the same question waiting to be asked again.
    """
    return session.get(Parent, parent_id) if parent_id is not None else None


@router.get("/parents")
def read_parents(session: Annotated[Session, Depends(get_session)]) -> list[ParentProfile]:
    """Both Parents, in seed order. There are exactly two, and the answer is the same
    for either of them: the Diary is jointly readable (ADR-0001)."""
    parents = session.scalars(select(Parent).order_by(Parent.position)).all()
    return [ParentProfile.model_validate(parent) for parent in parents]
