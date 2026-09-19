"""The Diary's tables.

One row per Answer and one per Skip, keyed by Parent, Prompt and Diary day; there is
no per-day container table, because with independent draws the two Parents' evenings
are ragged and a day is a query rather than a row (ADR-0004).
"""

from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Child(Base):
    """The person the Diary is about. Their birthdate is what makes every Answer
    displayable as an age years later (ADR-0002)."""

    __tablename__ = "children"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    birthdate: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Parent(Base):
    """One of the two people who answer. `position` is the seed's natural key: there
    are exactly two Parents and they are seeded, never created in the app."""

    __tablename__ = "parents"
    __table_args__ = (
        CheckConstraint("position in (1, 2)", name="ck_parents_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, unique=True)
    name: Mapped[str] = mapped_column(String(100))
    #: When this Parent's evening notification is due, in the family's timezone.
    notification_time: Mapped[time] = mapped_column(Time)
    #: The first Diary day the time above counts on, or nothing for the time it was
    #: seeded with, which has counted all along. Written whenever a Parent moves their
    #: own time, and it is tomorrow rather than today when the hour they chose has
    #: already gone by: that is a Parent asking for tomorrow evening, not for a
    #: notification a minute from now.
    notification_time_from: Mapped[date | None] = mapped_column(Date)


class Prompt(Base):
    """A question from the Prompt bank. Seeded from `docs/prompt-bank.md` and edited
    by changing the seed, never through the API (ADR-0004)."""

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Unique, so re-running the seed re-offers the same Prompt rather than a copy.
    text: Mapped[str] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Answer(Base):
    """What one Parent wrote for one Prompt on one Diary day.

    Media is not stored today; when it arrives it is a new table keyed by answer_id,
    so this shape does not have to change.
    """

    __tablename__ = "answers"
    __table_args__ = (
        # A Prompt already answered today is never drawn again that day, so the same
        # Parent cannot answer it twice on one Diary day.
        UniqueConstraint("parent_id", "prompt_id", "diary_day", name="uq_answers_parent_prompt_day"),
        Index("ix_answers_diary_day", "diary_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"))
    diary_day: Mapped[date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Skip(Base):
    """A Prompt declined on a Diary day. Kept rather than forgotten: it is what lets a
    Skip come back later the same evening, and the only way to learn which Prompts get
    reliably dodged (ADR-0004)."""

    __tablename__ = "skips"
    __table_args__ = (
        UniqueConstraint("parent_id", "prompt_id", "diary_day", name="uq_skips_parent_prompt_day"),
        Index("ix_skips_diary_day", "diary_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"))
    diary_day: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Delivery(Base):
    """The Prompt pushed to one Parent for one Diary day.

    At most one per Parent per Diary day, which is what makes "exactly one notification
    per evening" survive a scheduler restart, and it binds the notification to the
    Prompt the Sitting will open on.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("parent_id", "diary_day", name="uq_deliveries_parent_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"))
    diary_day: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    """One installed device. A Parent has as many as they have phones."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    #: The push service URL, unique per device and browser profile.
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh_key: Mapped[str] = mapped_column(Text)
    auth_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
