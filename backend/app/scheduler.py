"""The evening notification: one per Parent per Diary day, carrying a real Prompt.

This is the Compose service that wakes the house up. It runs the same image as the API
with a different command (ADR-0009) and no HTTP surface of its own — deliberately, and
not to save a service: a scheduler living inside a multi-worker API process fires its
job once per worker, both Parents get duplicates, and the fix is a lock nobody
remembers to keep. A separate process makes that bug structurally impossible.

Once a minute it asks what is due. Almost every pass has nothing to do; the ones that
have follow the same order every time, and the order is the whole design:

1. Is this Parent's time past, on the Diary day that is running now?
2. Is there already a Delivery for them on it? Then this evening is spent.
3. Has this Parent a Device at all, and a Prompt left to be asked?
4. **Record the Delivery, and commit it, before anything is sent.**
5. Send it to every Device they carry, and note that it went.

Step 4 is what a restart runs into. A scheduler that dies between recording and sending
costs that Parent one evening's notification; one that sent first and recorded after
would, on the same crash, wake them a second time with the same question. The second is
worse, so this is at-most-once on purpose and the row is written first.

`sent_at` tells the two apart afterwards: a Delivery with none is an evening that was
claimed and never arrived, which is a thing to find in the logs rather than a thing to
retry — by the time anybody looks, the evening it belonged to is over. A process that
dies halfway through step 5 loses that evening for *every* Device of that Parent, not
only the ones it had not reached yet: the row is already committed, and nothing is
retried. That is the same trade as step 4, taken a second time.
"""

import logging
import signal
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import FrameType

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.chance import Chance, Dice
from app.clock import Clock, SystemClock
from app.config import Settings
from app.db import create_session_factory
from app.diary_day import diary_day_of, end_of, moment_of
from app.draw import draw_for
from app.models import Delivery, Parent, PushSubscription
from app.notification_time import counts_on
from app.vapid import configured_vapid
from app.webpush import Device, Notification, PushFailed, PushSender, WebPush

# Named rather than taken from `__name__`, which is "__main__" in the process this
# module is run as: the scheduler's lines belong beside the API's `app.seed` in a
# `docker compose logs`, not under a name that says nothing about where they came from.
logger = logging.getLogger("app.scheduler")

#: How often to ask what is due. A minute is the resolution a notification time is set
#: at, and a pass with nothing to do is two small queries.
TICK = timedelta(minutes=1)

#: What the phone shows above the Prompt. The app's name rather than the Child's: a
#: notification is read on a lock screen, sometimes by whoever is nearest.
THE_APP = "Kidiary"


@dataclass(frozen=True)
class Evening:
    """One pass of the scheduler: the moment it is running at, and what it runs with.

    The same idea as `Tonight` in `sitting.py` — everything one Parent's turn needs,
    gathered so that "which Diary day is this" is decided once per pass rather than
    once per Parent.
    """

    session: Session
    now: datetime
    diary_day: date
    chance: Chance
    sender: PushSender


def send_what_is_due(
    session: Session, clock: Clock, chance: Chance, sender: PushSender
) -> None:
    """One pass. Every Parent whose evening has come and has not been delivered yet.

    Each Parent is handled inside its own guard, so that one of them failing — a push
    service having a bad night, a subscription the browser rotated — costs that Parent
    their notification and nobody else theirs.
    """
    now = clock.now()
    evening = Evening(session, now, diary_day_of(now), chance, sender)

    for parent in session.scalars(select(Parent).order_by(Parent.position)).all():
        try:
            _the_evening_of(parent, evening)
        except Exception:
            # Broad on purpose: this loop is the only thing standing between one
            # Parent's bad evening and the other's, and there is no caller above it
            # that could do anything more useful than log and carry on.
            session.rollback()
            logger.exception("No notification for %s on %s.", parent.name, evening.diary_day)


def _the_evening_of(parent: Parent, evening: Evening) -> None:
    session, diary_day = evening.session, evening.diary_day

    if not counts_on(parent, diary_day):
        # A time this Parent set tonight, for an hour that had already gone by. They
        # were asking for tomorrow evening rather than for a notification a minute
        # later, and `notification_time.py` wrote down which evening they meant.
        return

    if evening.now < moment_of(diary_day, parent.notification_time, evening.now.tzinfo):
        return

    already = session.scalar(
        select(Delivery.id).where(
            Delivery.parent_id == parent.id, Delivery.diary_day == diary_day
        )
    )
    if already is not None:
        return

    devices = _devices_of(session, parent)
    if not devices:
        # Nothing to send to, and nothing recorded either: a Parent who switches their
        # phone on at half past nine is asking for tonight's notification, and an
        # evening already marked delivered would have been spent on nobody.
        return

    prompt = draw_for(session, parent.id, diary_day, evening.chance)
    if prompt is None:
        logger.info(
            "%s has answered the whole bank for %s; there is nothing to ask.",
            parent.name,
            diary_day,
        )
        return

    # The evening is claimed here, before a single byte goes out. `on_conflict_do_nothing`
    # rather than a plain insert because the unique constraint is the real guard: two
    # passes overlapping, or a second scheduler started by accident, find the row taken
    # and stop rather than raising.
    recorded = session.execute(
        pg_insert(Delivery)
        .values(parent_id=parent.id, prompt_id=prompt.id, diary_day=diary_day)
        .on_conflict_do_nothing(constraint="uq_deliveries_parent_day")
        .returning(Delivery.id)
    ).scalar_one_or_none()
    session.commit()
    if recorded is None:
        return

    notification = Notification(
        title=THE_APP,
        body=prompt.text,
        expires_in=end_of(diary_day, evening.now.tzinfo) - evening.now,
    )
    reached = sum(_reached(device, notification, parent, evening) for device in devices)

    if reached:
        session.execute(
            update(Delivery).where(Delivery.id == recorded).values(sent_at=evening.now)
        )
        session.commit()
        logger.info("%s was asked \"%s\" on %s.", parent.name, prompt.text, diary_day)
    else:
        logger.warning("%s could not be reached at all on %s.", parent.name, diary_day)


def _reached(
    device: Device, notification: Notification, parent: Parent, evening: Evening
) -> bool:
    """Send to one Device, and say whether it arrived.

    A failure here is one Device of the several a Parent carries. A tablet that has
    been off for a month must not silence the phone in their hand, so it is a line in
    the log and the next Device is still tried.
    """
    try:
        evening.sender.send(device, notification)
    except PushFailed as refused:
        logger.warning("%s was not reached at %s: %s", parent.name, device.endpoint, refused)
        if refused.device_is_gone:
            _forget(device, evening.session)
        return False
    return True


def _forget(device: Device, session: Session) -> None:
    """Drop a subscription the push service says no longer exists.

    410 is the one refusal that is about the row rather than the request: the app was
    deleted, its site data cleared, or the subscription expired, and nothing will ever
    be delivered to that endpoint again. Keeping it would mean pushing at it every
    evening for years, and it would read — to anybody looking at the table — like a
    Parent who has notifications on. A Device that is still there registers again on
    its next open (`push.ts`), so this costs nothing that has not already gone.
    """
    logger.info("Forgetting %s, which the push service says is gone.", device.endpoint)
    session.execute(delete(PushSubscription).where(PushSubscription.endpoint == device.endpoint))
    session.commit()


def _devices_of(session: Session, parent: Parent) -> list[Device]:
    """Every Device this Parent carries, copied out of the rows.

    Copied rather than passed on as ORM objects because the send happens after a commit
    and outside anything the session is holding: what a push needs is three strings.
    """
    return [
        Device(
            endpoint=subscription.endpoint,
            p256dh_key=subscription.p256dh_key,
            auth_key=subscription.auth_key,
        )
        for subscription in session.scalars(
            select(PushSubscription)
            .where(PushSubscription.parent_id == parent.id)
            .order_by(PushSubscription.id)
        )
    ]


def run(settings: Settings | None = None) -> None:
    """The loop, until the container is told to stop.

    It builds its own clock, its own randomness and its own session factory rather than
    sharing the API's: this is a second process, and the only thing the two have in
    common is the database and the image they were built from.
    """
    settings = settings or Settings()
    session_factory = create_session_factory(settings.database_url)
    clock = SystemClock(settings.timezone)
    chance = Dice()

    stopping = _stop_on_a_signal()

    # A malformed pair stops this process the same way it stops the API (`vapid.py`).
    vapid = configured_vapid(settings)
    if vapid is None:
        # Nothing to do, ever, until somebody puts a pair in `.env` and restarts. It
        # waits to be stopped rather than exiting, because a container that exits under
        # `restart: unless-stopped` comes back a second later to say the same thing.
        logger.warning(
            "No VAPID keys, so no notification can be sent. The rest of the stack works; "
            "see docs/push-notifications.md to generate a pair."
        )
        stopping.wait()
        return

    sender = WebPush(vapid)
    logger.info("Watching for evenings, every %s.", TICK)

    while not stopping.is_set():
        try:
            with session_factory() as session:
                send_what_is_due(session, clock, chance, sender)
        except Exception:
            # Most often a database that is not up yet: this service and the API start
            # together, and the API migrates. A pass that failed is a pass skipped, and
            # the next one is a minute away.
            logger.exception("The evening pass failed; trying again next tick.")
        stopping.wait(TICK.total_seconds())

    logger.info("Stopped.")
    sender.close()


def _stop_on_a_signal() -> threading.Event:
    """Wake the sleep below up when Compose says stop, rather than making it wait out
    the tick and be killed."""
    stopping = threading.Event()

    def stop(number: int, frame: FrameType | None) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    return stopping


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()
