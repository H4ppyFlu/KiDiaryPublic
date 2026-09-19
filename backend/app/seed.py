"""What the database has to know before the Diary can be used: who it is about, who
keeps it, and what it can ask.

The Prompt bank is copied from `docs/prompt-bank.md`; that file is the source of truth
and this list must be kept in step with it. Prompts are edited by changing this seed and
restarting, never through the API (ADR-0004).

Seeding runs on every start and is idempotent. For the Child and the Parents it only
ever adds: a Child already on record is never rewritten from configuration, because a
birthdate that has been captured cannot be reconstructed (ADR-0002) and a stack restarted
without its `.env` would otherwise quietly replace it with a placeholder. Where the two
disagree, the record wins and the disagreement is logged.

The Prompt bank is the exception, and has to be: editing the seed is the *only* way to
edit it, so a Prompt taken out of the list here has to stop being asked. It is retired
rather than deleted — Answers, Skips and Deliveries all carry its id, and the Diary exists
to keep exactly those — and a Prompt put back into the list is asked again.
"""

import logging
from datetime import time

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.child import the_child
from app.config import Settings
from app.models import Child, Parent, Prompt

logger = logging.getLogger(__name__)

PROMPT_BANK = (
    "Was war heute schön?",
    "Was war heute neu?",
    "Welcher Moment von heute soll bleiben?",
    "Welchen Satz von heute willst du nicht vergessen?",
    "Womit wurde heute am liebsten gespielt?",
    "Was hast du heute über dein Kind gelernt?",
    "Wo wart ihr heute zusammen?",
    "Was wurde heute zum ersten Mal alleine geschafft?",
    "Was hat dich heute stolz gemacht?",
    "Was würdest du später über den heutigen Tag erzählen?",
    "Was war heute witzig?",
)

#: Where both Parents' evening notification starts out. Each Parent moves their own
#: later, from inside the app.
INITIAL_NOTIFICATION_TIME = time(20, 0)


def seed(session: Session, settings: Settings) -> None:
    _seed_child(session, settings)
    _seed_parents(session, settings)
    _seed_prompts(session)
    session.commit()


def _seed_child(session: Session, settings: Settings) -> None:
    child = the_child(session)
    if child is None:
        # Said out loud, because this is the moment a placeholder from an absent `.env`
        # would become the Child on record.
        logger.info(
            "Recording the Child %s, born %s.", settings.child_name, settings.child_birthdate
        )
        session.add(Child(name=settings.child_name, birthdate=settings.child_birthdate))
        return

    if (child.name, child.birthdate) != (settings.child_name, settings.child_birthdate):
        logger.warning(
            "The Child on record is %s, born %s, but configuration says %s, born %s. "
            "The record stands; change it in the database if it is really wrong.",
            child.name,
            child.birthdate,
            settings.child_name,
            settings.child_birthdate,
        )


def _seed_parents(session: Session, settings: Settings) -> None:
    """Exactly two Parents, identified by their position."""
    configured = dict(enumerate((settings.parent_one_name, settings.parent_two_name), start=1))

    statement = insert(Parent).values(
        [
            {
                "position": position,
                "name": name,
                "notification_time": INITIAL_NOTIFICATION_TIME,
            }
            for position, name in configured.items()
        ]
    )
    session.execute(statement.on_conflict_do_nothing(index_elements=[Parent.position]))
    session.flush()

    for parent in session.scalars(select(Parent)):
        if parent.name != configured[parent.position]:
            logger.warning(
                "Parent %d is %s on record but %s in configuration. The record stands.",
                parent.position,
                parent.name,
                configured[parent.position],
            )


def _seed_prompts(session: Session) -> None:
    """Bring the bank in the database to what `PROMPT_BANK` says it is.

    Three things, in the order they have to happen: add what the list has gained, never a
    second copy of a Prompt already there, and retire what the list has lost.

    Retired rather than deleted. `answers`, `skips` and `deliveries` all carry a
    `prompt_id`, and the Diary is the thing this project exists to keep — a Prompt that was
    asked in March is part of what was written in March, whatever the bank says in
    September. `is_active` is what `draw.py` filters on, so clearing it is the whole of
    "stop asking this" and nothing else changes.

    The reverse is true too: a Prompt written back into the list is asked again rather than
    added a second time, because the row is still there under the same unique text.
    """
    statement = insert(Prompt).values([{"text": text} for text in PROMPT_BANK])
    session.execute(statement.on_conflict_do_nothing(index_elements=[Prompt.text]))

    retired = session.scalars(
        update(Prompt)
        .where(Prompt.text.not_in(PROMPT_BANK), Prompt.is_active)
        .values(is_active=False)
        .returning(Prompt.text)
    ).all()
    for text in retired:
        # Said out loud, because a Prompt silently disappearing from the evenings is
        # indistinguishable from a draw that has gone wrong.
        logger.info("Retired from the Prompt bank, and no longer asked: %r", text)

    asked_again = session.scalars(
        update(Prompt)
        .where(Prompt.text.in_(PROMPT_BANK), ~Prompt.is_active)
        .values(is_active=True)
        .returning(Prompt.text)
    ).all()
    for text in asked_again:
        logger.info("Back in the Prompt bank, and asked again: %r", text)
