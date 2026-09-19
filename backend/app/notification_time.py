"""When a Parent's evening notification arrives, and what moving it means.

Each Parent has their own time and neither can see or change the other's: one shared
hour would land in the middle of one of the two bedtimes, and a Diary kept by two
people at once is exactly the thing that must not make them keep the same evening.

The whole of the thinking here is in one rule. A time is a time of day, so moving it
says nothing by itself about *which* evening the move is for, and there are two
readings of somebody typing 20:00 at nine in the evening:

- "Send it now" — the hour has come, and the pass a minute from now would agree.
- "Send it at eight, from tomorrow" — which is what a person setting a bedtime means.

The second is the one a Parent means, so an hour that has already gone by counts from
the next Diary day (`counts_from`). An hour still ahead counts tonight, which needs no
rule: 22:00 typed at nine is a Parent asking to be asked at ten.

That is also why `parents.notification_time_from` exists at all. The scheduler cannot
work the difference out from the time alone — 20:00 looks the same whether it was set a
year ago or a minute ago — so the answer is written down when the Parent says it, and
the scheduler only reads it.

The rule lives here rather than beside the endpoint that writes it because both halves
of the feature need it and they are not the same kind of thing: `push.py` asks it what a
Parent has just said, and `scheduler.py` — a separate process with no request, no cookie
and no FastAPI in it (ADR-0009) — asks it whether tonight is an evening this time counts
on. The same split, and for the same reason, as `draw.py`.
"""

from datetime import date, datetime, time, timedelta

from app.diary_day import diary_day_of, moment_of
from app.models import Parent


def counts_from(now: datetime, wanted: time) -> date:
    """The first Diary day a Parent who says `wanted` now is asking to be asked on.

    Today's Diary day while the hour is still ahead — 22:00 typed at nine is tonight at
    ten — and the next one once it has gone by. `moment_of` is what makes that true
    after midnight as well: on the Diary day that is running at 01:30, an hour of 20:00
    was five and a half hours ago and one of 02:00 is half an hour away.
    """
    diary_day = diary_day_of(now)
    if now < moment_of(diary_day, wanted, now.tzinfo):
        return diary_day
    return diary_day + timedelta(days=1)


def counts_on(parent: Parent, diary_day: date) -> bool:
    """Whether this Parent's notification time is in force on this Diary day.

    Nothing recorded means the seeded time, which has counted since the first evening.
    """
    return parent.notification_time_from is None or parent.notification_time_from <= diary_day
