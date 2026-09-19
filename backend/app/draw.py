"""Choosing the next Prompt for one Parent, and nothing else.

This is ADR-0004's rule in full: one filter and three orderings. A Prompt this Parent
has already answered this Diary day is out; of what is left, one not yet seen tonight
comes before one skipped tonight; within that, the one this Parent answered longest ago
— never answered counts as longest of all — comes first; and where the rules still do
not prefer one Prompt over another, `Chance` picks.

It lives here rather than in `sitting.py` because two callers need it now and they are
not the same kind of thing. The Sitting draws when a phone asks; the scheduler draws in
the evening, hours before anybody opens the app, to put a real Prompt in the
notification. A notification carrying a Prompt the Sitting would not have offered is a
notification that lies, so both go through this one function.

Every clause reads only this Parent's rows, which is what keeps the two evenings
independent (ADR-0004): what one of them has answered tonight says nothing about what
the other is shown.
"""

from datetime import date

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.chance import Chance
from app.models import Answer, Prompt, Skip


def draw_for(session: Session, parent_id: int, diary_day: date, chance: Chance) -> Prompt | None:
    """The next Prompt for this Parent on this Diary day, or nothing if it is complete.

    Nothing means every Prompt in the bank has been answered today. Skipping never
    empties the bank — a skipped Prompt comes back — so that is reached by answering the
    last one, never by passing over them all.
    """
    answered_today = select(Answer.prompt_id).where(
        Answer.parent_id == parent_id, Answer.diary_day == diary_day
    )
    skipped_tonight = Prompt.id.in_(
        select(Skip.prompt_id).where(Skip.parent_id == parent_id, Skip.diary_day == diary_day)
    )
    last_answered = (
        select(Answer.prompt_id.label("prompt_id"), func.max(Answer.diary_day).label("day"))
        .where(Answer.parent_id == parent_id)
        .group_by(Answer.prompt_id)
        .subquery()
    )

    candidates = session.execute(
        select(
            Prompt,
            skipped_tonight.label("skipped_tonight"),
            last_answered.c.day.label("last_answered"),
        )
        .outerjoin(last_answered, last_answered.c.prompt_id == Prompt.id)
        .where(Prompt.is_active, Prompt.id.not_in(answered_today))
        .order_by(
            # False sorts before true: a Prompt not yet seen tonight comes ahead of one
            # already skipped tonight, and a skipped one is offered again only once the
            # unseen have run out.
            skipped_tonight,
            # A Prompt this Parent has never answered has no last time, and no last time
            # is the longest ago there is. Postgres sorts nulls last when sorting up, so
            # saying this is what makes the rule true rather than inverted.
            last_answered.c.day.asc().nulls_first(),
            # Nothing in the rules says which of two tied Prompts to prefer, but the
            # rows must reach `Chance` in the same order every time, or a seeded source
            # is not reproducible.
            Prompt.id,
        )
    ).all()

    if not candidates:
        return None

    def as_far_as_the_rules_got(row: Row) -> tuple[bool, date | None]:
        """How much the sort managed to say about this Prompt. Two rows that agree here
        are equally eligible, and nothing but chance separates them."""
        return row.skipped_tonight, row.last_answered

    # A bank of twenty is small enough to find the tied ones by reading the rows back
    # rather than by writing the same comparison a second time in SQL.
    front = as_far_as_the_rules_got(candidates[0])
    tied = [row.Prompt for row in candidates if as_far_as_the_rules_got(row) == front]
    return chance.pick(tied)
