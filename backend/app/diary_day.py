"""Which day an Answer belongs to.

A Diary day runs 04:00 to 04:00 in the family's timezone rather than midnight to
midnight (ADR-0004): parents of small children are awake at hours that do not respect
calendars, so an Answer written at 01:30 belongs to the evening that just ended and not
to the day that has just begun.

This is the whole of the rule. "Today" means a Diary day everywhere in the app except
the Child's age, which is the calendar's business.
"""

from datetime import date, datetime, time, timedelta, tzinfo

#: When one Diary day gives way to the next, in local time.
DAY_BEGINS = time(4, 0)


def diary_day_of(moment: datetime) -> date:
    """The Diary day a moment falls in. The moment is local time — what `Clock` hands
    out — because 04:00 means 04:00 where the family lives."""
    if moment.time() < DAY_BEGINS:
        return moment.date() - timedelta(days=1)
    return moment.date()


def moment_of(diary_day: date, local_time: time, where: tzinfo | None) -> datetime:
    """A time of day, on a Diary day, as a moment.

    The inverse of `diary_day_of`, and the reason it is not one line: a Diary day is
    only the same thing as the calendar day it is named by between 04:00 and midnight.
    A notification time of 20:00 falls on that calendar day; one of 02:00 falls on the
    next. The scheduler is where this matters, and the rule belongs here with the rest
    of it rather than beside its caller.
    """
    calendar_day = diary_day if local_time >= DAY_BEGINS else diary_day + timedelta(days=1)
    return datetime.combine(calendar_day, local_time, tzinfo=where)


def end_of(diary_day: date, where: tzinfo | None) -> datetime:
    """The moment this Diary day gives way to the next: 04:00, local time."""
    return datetime.combine(diary_day + timedelta(days=1), DAY_BEGINS, tzinfo=where)
