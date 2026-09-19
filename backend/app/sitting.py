"""One Prompt at a time, and the Answer or Skip that draws the next one.

A Sitting is one stretch of answering: a Parent is shown a single Prompt, answers it or
passes over it, and either act draws the next. There is no form of several questions and
no per-day container — a Diary day is a query over Answers, not a row (ADR-0004).

The rule the draw follows is `draw.py`, which the evening scheduler draws through as
well: the Prompt a notification carries has to be the Prompt the app would have offered.

A Sitting opened by tapping the evening notification opens on that Prompt rather than on
a fresh draw — the notification showed a question, and a phone that then asks a different
one has told a small lie about the Diary's own record. Which Prompt that was is not
something the phone says; it is the Delivery the scheduler wrote before it sent anything
(`the_delivered_prompt`). Everything after that first Prompt is the ordinary draw.
"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_parent
from app.chance import Chance, get_chance
from app.clock import Clock, get_clock
from app.db import get_session
from app.diary_day import diary_day_of
from app.draw import draw_for
from app.models import Answer, Delivery, Parent, Prompt, Skip

router = APIRouter()


@dataclass(frozen=True)
class Tonight:
    """One request's answer to "who is writing, and which Diary day is it?".

    Not a Sitting: a Sitting runs across many requests and the app remembers none of it.
    This is what each endpoint below needs before it can do anything, gathered so that
    "which Diary day is this" is decided in one place rather than three.
    """

    parent: Parent
    diary_day: date
    session: Session
    chance: Chance


def tonight(
    parent: Annotated[Parent, Depends(require_parent)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    chance: Annotated[Chance, Depends(get_chance)],
) -> Tonight:
    return Tonight(parent, diary_day_of(clock.now()), session, chance)


class DrawnPrompt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str


class Draw(BaseModel):
    """What is in front of the Parent now.

    A null Prompt means this Diary day is complete: every Prompt in the bank has been
    answered. Skipping never empties the bank — a skipped Prompt comes back — so this is
    reached by answering the last one, never by passing over them all.
    """

    prompt: DrawnPrompt | None


def draw(tonight: Tonight) -> Draw:
    """The next Prompt for this Parent tonight, or nothing if the Diary day is done."""
    prompt = draw_for(tonight.session, tonight.parent.id, tonight.diary_day, tonight.chance)
    return Draw(prompt=DrawnPrompt.model_validate(prompt) if prompt is not None else None)


def the_delivered_prompt(evening: Tonight) -> Prompt | None:
    """The Prompt tonight's notification carried, if it is still a question to ask.

    Nothing, and an ordinary draw instead, in every case where opening it would be
    worse than opening something else:

    - **No Delivery on this Diary day.** The app was opened by hand, the evening's
      notification has not gone out yet, or the tap came the next morning on a
      notification about an evening that is over.
    - **It has been answered since.** The other device got there first, or the Parent
      answered it and came back to the notification still sitting on the lock screen.
      Answering it again is refused by the database anyway (`write_answer`).
    - **It has left the bank.** A Prompt retired between the push and the tap.

    A Prompt *skipped* since is still offered: skipping is a "not now" and never empties
    the bank (ADR-0004), and a Parent who passed over it at eight and then tapped the
    notification at ten is asking for the question it showed.
    """
    delivered = evening.session.scalar(
        select(Prompt)
        .join(Delivery, Delivery.prompt_id == Prompt.id)
        .where(
            Delivery.parent_id == evening.parent.id,
            Delivery.diary_day == evening.diary_day,
            Prompt.is_active,
        )
    )
    if delivered is None:
        return None

    answered_already = evening.session.scalar(
        select(Answer.id).where(
            Answer.parent_id == evening.parent.id,
            Answer.prompt_id == delivered.id,
            Answer.diary_day == evening.diary_day,
        )
    )
    return None if answered_already is not None else delivered


@router.get("/prompt")
def read_prompt(
    evening: Annotated[Tonight, Depends(tonight)],
    from_the_notification: bool = False,
) -> Draw:
    """The Prompt to answer now. Asked when the app opens, when a Sitting is picked up
    again, and after a reload mid-Sitting — a draw is not remembered anywhere, so asking
    for one is how the app finds out what is left of the evening.

    `from_the_notification` is the one thing a phone can say about *why* it is asking,
    and it is set only by an open that came from a tap (`notificationTap.ts`). It asks
    for the delivered Prompt where there still is one, and for a draw where there is
    not — so a phone never has to know which of the two it is getting, and cannot name
    the Prompt it would like either way.
    """
    if from_the_notification:
        delivered = the_delivered_prompt(evening)
        if delivered is not None:
            return Draw(prompt=DrawnPrompt.model_validate(delivered))
    return draw(evening)


def prompt_in_the_bank(session: Session, prompt_id: int) -> Prompt:
    """The Prompt a phone named, or a 404. A Prompt retired from the bank is refused
    the same way one that never existed is: neither is a question the app is asking."""
    prompt = session.get(Prompt, prompt_id)
    if prompt is None or not prompt.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such Prompt in the bank."
        )
    return prompt


class Submission(BaseModel):
    prompt_id: int
    text: str

    @field_validator("text")
    @classmethod
    def _must_say_something(cls, text: str) -> str:
        """Whitespace is not an Answer. Skipping a Prompt is a separate act with its
        own record; submitting nothing must not masquerade as one."""
        written = text.strip()
        if not written:
            raise ValueError("An Answer cannot be empty.")
        return written


@router.post("/answers", status_code=status.HTTP_201_CREATED)
def write_answer(
    submission: Submission,
    evening: Annotated[Tonight, Depends(tonight)],
) -> Draw:
    """Store an Answer against this Parent, this Prompt and this Diary day, and draw
    the next Prompt in the same breath — that is one round trip on a phone rather
    than two."""
    session = evening.session
    prompt = prompt_in_the_bank(session, submission.prompt_id)

    session.add(
        Answer(
            parent_id=evening.parent.id,
            prompt_id=prompt.id,
            diary_day=evening.diary_day,
            text=submission.text,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # The one row per Parent, Prompt and Diary day is a database constraint, so
        # two phones submitting the same Prompt at once end here rather than doubling
        # it. The draw already excludes it; reaching this means a stale screen.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That Prompt has already been answered today.",
        ) from None

    return draw(evening)


class Skipped(BaseModel):
    """The Prompt being passed over. No text, which is the whole difference between a
    Skip and the empty Answer refused above: one is on record, the other is nothing."""

    prompt_id: int


@router.post("/skips", status_code=status.HTTP_201_CREATED)
def skip_prompt(
    skipped: Skipped,
    evening: Annotated[Tonight, Depends(tonight)],
) -> Draw:
    """Record the Skip and draw the next Prompt, in the shape `POST /answers` has:
    skipping a Prompt continues the Sitting rather than ending it."""
    session = evening.session
    prompt = prompt_in_the_bank(session, skipped.prompt_id)

    answered_already = session.scalar(
        select(Answer.id).where(
            Answer.parent_id == evening.parent.id,
            Answer.prompt_id == prompt.id,
            Answer.diary_day == evening.diary_day,
        )
    )
    if answered_already is not None:
        # Only a stale screen can ask this, and the same refusal `POST /answers` gives
        # it. A Prompt must never be both answered and skipped on one Diary day: a Skip
        # is the record of what gets dodged, and one on top of an Answer is noise in it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That Prompt has already been answered today.",
        )

    session.execute(
        pg_insert(Skip)
        .values(parent_id=evening.parent.id, prompt_id=prompt.id, diary_day=evening.diary_day)
        # A skipped Prompt comes back later the same evening and may be passed over a
        # second time. That is the rule working, not a conflict, so the row already
        # there stands and the Sitting moves on.
        .on_conflict_do_nothing(constraint="uq_skips_parent_prompt_day")
    )
    session.commit()

    return draw(evening)
