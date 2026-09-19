from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.age import Age, age_on
from app.clock import Clock, get_clock
from app.db import get_session
from app.models import Child

router = APIRouter()


def the_child(session: Session) -> Child | None:
    """The Child the Diary is about.

    Modelled as an entity so a second one needs no reshaping (ADR-0002), but there is
    one in practice, and this is the single place that says so.
    """
    return session.scalars(select(Child).order_by(Child.id).limit(1)).one_or_none()


class ChildProfile(BaseModel):
    name: str
    birthdate: date
    age: Age


@router.get("/child")
def read_child(
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ChildProfile:
    """Who the Diary is about, and how old they are today.

    Today is the calendar date rather than the Diary day: at 01:30 on a birthday the
    Child has had their birthday, even though the Answer written then belongs to the
    evening before.
    """
    child = the_child(session)
    if child is None:
        # Only reachable if the seed never ran; the Diary has nothing to be about.
        raise HTTPException(status_code=404, detail="No child has been seeded.")

    return ChildProfile(
        name=child.name,
        birthdate=child.birthdate,
        age=age_on(child.birthdate, clock.now().date()),
    )
