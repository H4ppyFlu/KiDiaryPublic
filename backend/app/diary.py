"""The Diary: everything both Parents have written, read back.

The Sitting writes; this reads. There is one Diary rather than one per Parent, and
neither of them has a private corner of it (ADR-0001) — so this endpoint takes no
account of who is asking, and both Parents get the same bytes.

It comes back as Diary days rather than as a flat run of Answers, because a Diary day
is the unit the archive is actually made of (ADR-0004): the date and the Child's age
belong to the evening, not to each sentence written in it, and both Parents' Answers
sit under the same heading — which is what makes the Diary read as shared rather than
as two accounts side by side.

Everything, in one response. The bank holds twenty Prompts and there are two Parents,
so a decade of diligent evenings is a five-figure row count at the very worst; paging
is machinery to add the first time a phone notices, not before.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.age import Age, age_on
from app.child import the_child
from app.db import get_session
from app.models import Answer, Parent, Prompt
from app.parents import ParentProfile

router = APIRouter()


class DiaryEntry(BaseModel):
    """One Answer as it is read years later.

    The Prompt is carried rather than referenced: a bare sentence stops making sense
    within a year, and the question it answered is what keeps it readable.
    """

    id: int
    prompt: str
    author: ParentProfile
    text: str


class DiaryDay(BaseModel):
    """One evening, and how old the Child was on it.

    The age is derived here rather than stored, from the birthdate captured once
    (ADR-0002). It is the label that makes the archive read as a record of a person
    growing up rather than as a list of dates.
    """

    diary_day: date
    age: Age
    answers: list[DiaryEntry]


class TheDiary(BaseModel):
    """Newest evening first: the one being read is nearly always the one just gone.

    An empty list is the ordinary state of the first evening, not an error — the phone
    has to have something to render before anybody has written anything.
    """

    days: list[DiaryDay]


@router.get("/diary")
def read_diary(session: Annotated[Session, Depends(get_session)]) -> TheDiary:
    """Every Answer both Parents have written, newest evening first.

    Behind the PIN like everything else, but not behind the Parent claim: reading the
    Diary is not done in anyone's name, and a device that has not yet said who is
    holding it is still a device the family unlocked (ADR-0010).
    """
    child = the_child(session)
    if child is None:
        # Only reachable if the seed never ran; there is no Child for the ages to be
        # about, and an archive that cannot say how old they were is not this one.
        raise HTTPException(status_code=404, detail="No child has been seeded.")

    written = session.execute(
        select(Answer, Prompt.text, Parent)
        .join(Prompt, Prompt.id == Answer.prompt_id)
        .join(Parent, Parent.id == Answer.parent_id)
        # Newest evening first, and within an evening the sentence written last comes
        # first — the same rule twice, so that reading down the page is reading back
        # through time without a break at the day boundary.
        .order_by(Answer.diary_day.desc(), Answer.created_at.desc(), Answer.id.desc())
    ).all()

    days: list[DiaryDay] = []
    for answer, prompt_text, parent in written:
        # The rows arrive grouped by the sort, so a new Diary day is simply a row whose
        # day is not the one being filled.
        if not days or days[-1].diary_day != answer.diary_day:
            days.append(
                DiaryDay(
                    diary_day=answer.diary_day,
                    age=age_on(child.birthdate, answer.diary_day),
                    answers=[],
                )
            )
        days[-1].answers.append(
            DiaryEntry(
                id=answer.id,
                prompt=prompt_text,
                author=ParentProfile.model_validate(parent),
                text=answer.text,
            )
        )

    return TheDiary(days=days)
