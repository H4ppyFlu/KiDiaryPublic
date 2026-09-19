"""The evening notification's two settings: which devices it wakes, and when it comes.

They are the two halves of one screen in the app and of one question a Parent has — "do
I get asked, and when?" — but they are not the same kind of thing, and the difference is
the whole of this module.

**Which devices** is per device. A Device is one phone or browser that has been given
the PIN, and each one subscribes separately: a Parent carrying two phones is two rows
here, and the scheduler sends to all of them. The push service's endpoint is what names
a device — it is unique per device and browser profile, and the browser hands it back
unchanged every time — so it is the natural key, and re-registering the same phone
updates its row rather than adding one beside it.

**When** is per Parent. It is a column on `parents` and the only one the app ever lets
anybody write; a Parent moving it moves it for every device they carry and for none of
their partner's (user story 25). What moving it *means* — and why an hour that has
already gone by is a request for tomorrow — is `notification_time.py`.

Here rather than in `parents.py`, which is where a Parent's own column would otherwise
belong: `auth.py` imports `parents.py` for `ParentProfile` and `the_parent`, so a
`parents.py` that imported `require_parent` back would be an import cycle. That is worth
saying out loud, because moving them there is the obvious suggestion and it does not
compile.

Nothing here asks a browser for permission; that is a tap in the app (`push.ts`), and
it has to be, because a permission prompt on load is a prompt that gets dismissed and
on iOS there is no second one without reinstalling the app.
"""

from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import require_parent
from app.clock import Clock, get_clock
from app.db import get_session
from app.diary_day import diary_day_of
from app.models import Parent, PushSubscription
from app.notification_time import counts_from, counts_on
from app.vapid import Vapid

router = APIRouter()


def get_vapid(request: Request) -> Vapid | None:
    vapid: Vapid | None = request.app.state.vapid
    return vapid


def require_vapid(vapid: Annotated[Vapid | None, Depends(get_vapid)]) -> Vapid:
    """For the endpoints that are meaningless without a key pair. A stack without one
    is a deployment that has not been set up rather than a request that was wrong."""
    if vapid is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This stack has no VAPID keys, so it cannot send notifications.",
        )
    return vapid


class PushKey(BaseModel):
    """What a browser needs before it may subscribe at all.

    Null when this stack has no keys, which is a screen rather than an error: the app
    says notifications are not set up here instead of offering a button that cannot work.
    """

    public_key: str | None


@router.get("/push/key")
def read_push_key(vapid: Annotated[Vapid | None, Depends(get_vapid)]) -> PushKey:
    """The public half, for `applicationServerKey`. Public by name and by nature — it
    is handed to every push service the browser talks to — but still behind the PIN,
    like everything else the app answers."""
    return PushKey(public_key=vapid.public_key if vapid else None)


def written_out(value: str) -> str:
    """The value with its whitespace trimmed, refusing what is left of nothing.

    Shared by the three fields below because all three mean the same thing: a
    subscription missing any one of them is a row the scheduler could never send to.
    """
    written = value.strip()
    if not written:
        raise ValueError("A subscription needs an endpoint and both of its keys.")
    return written


class SubscriptionKeys(BaseModel):
    """The two secrets the push payload is encrypted to, straight from the browser."""

    p256dh: str
    auth: str

    @field_validator("p256dh", "auth")
    @classmethod
    def _must_say_something(cls, key: str) -> str:
        return written_out(key)


class DeviceSubscription(BaseModel):
    """Exactly the shape `PushSubscription.toJSON()` hands back in the browser, so the
    app posts what it was given rather than taking it apart first."""

    # `expirationTime` comes along in that JSON and means nothing to us.
    model_config = ConfigDict(extra="ignore")

    endpoint: str
    keys: SubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _must_be_a_push_service(cls, endpoint: str) -> str:
        """A push endpoint is always an https URL at the browser vendor's service.
        Refusing anything else keeps a typo out of the table the scheduler sends from."""
        written = written_out(endpoint)
        if not written.startswith("https://"):
            raise ValueError("A push endpoint is an https URL.")
        return written


@router.put("/push/subscription", status_code=status.HTTP_204_NO_CONTENT)
def register_subscription(
    subscription: DeviceSubscription,
    parent: Annotated[Parent, Depends(require_parent)],
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[Vapid, Depends(require_vapid)],
) -> Response:
    """Store this device's subscription against the Parent holding it.

    A PUT because the app sends it whenever it opens with permission already granted,
    not only when a Parent taps the button: that is what repairs a Pi restored from a
    backup older than the row, and what catches a subscription the browser rotated
    underneath the app.
    """
    session.execute(
        pg_insert(PushSubscription)
        .values(
            parent_id=parent.id,
            endpoint=subscription.endpoint,
            p256dh_key=subscription.keys.p256dh,
            auth_key=subscription.keys.auth,
        )
        # The endpoint is unique, so the same phone arriving twice lands here. The keys
        # are overwritten because a re-subscribed device generates new ones, and the
        # Parent is overwritten because a phone that changed hands said so.
        .on_conflict_do_update(
            index_elements=[PushSubscription.endpoint],
            set_={
                "parent_id": parent.id,
                "p256dh_key": subscription.keys.p256dh,
                "auth_key": subscription.keys.auth,
            },
        )
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class UnsubscribingDevice(BaseModel):
    """The device letting go. Only its endpoint, because that is what names it."""

    endpoint: str

    @field_validator("endpoint")
    @classmethod
    def _must_say_something(cls, endpoint: str) -> str:
        return written_out(endpoint)


@router.delete("/push/subscription", status_code=status.HTTP_204_NO_CONTENT)
def forget_subscription(
    device: UnsubscribingDevice,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Stop sending to this device. Sent after the browser has unsubscribed, so the row
    is already dead: what is left is to stop the scheduler pushing at an endpoint that
    will only answer 410. It drops such a row itself when a push service says so, but
    only after wasting an evening's notification on it.

    The endpoint travels in the body rather than in the URL because it is a capability
    — anything holding it can push to that phone — and a URL ends up in access logs.

    Deleted by endpoint alone, without asking which Parent the row names. A device that
    claimed the other Parent between registering and turning notifications off is
    exactly the case that would otherwise leave a row nobody can reach behind, and the
    device saying it has unsubscribed is the authority on that either way.
    """
    session.execute(delete(PushSubscription).where(PushSubscription.endpoint == device.endpoint))
    session.commit()
    # Deleting nothing is the same answer: a device turning off notifications it never
    # turned on has got what it asked for.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class NotificationTime(BaseModel):
    """When this Parent is asked, and whether that is still to come tonight.

    `counts_tonight` is false only after a Parent has moved their time to an hour that
    had already gone by, which is a thing the screen has to say out loud: a Parent who
    is not told would spend the evening waiting for a notification that is a day away.
    """

    time: time
    counts_tonight: bool

    @field_serializer("time")
    def _to_the_minute(self, at: time) -> str:
        """`20:00` — the resolution the scheduler works at, and the shape an
        `<input type="time">` both speaks and understands."""
        return at.strftime("%H:%M")


class AChosenTime(BaseModel):
    """The hour a Parent typed. Local time, like every other time in the app."""

    time: time

    @field_validator("time")
    @classmethod
    def _local_and_to_the_minute(cls, at: time) -> time:
        if at.tzinfo is not None:
            raise ValueError("A notification time is local time, without an offset.")
        # The pass runs once a minute, so seconds are a resolution the scheduler could
        # not honour and a phone never sends. Dropped rather than refused: nothing about
        # what 20:00:30 means is in doubt.
        return at.replace(second=0, microsecond=0)


def the_notification_time_of(parent: Parent, now: datetime) -> NotificationTime:
    return NotificationTime(
        time=parent.notification_time,
        counts_tonight=counts_on(parent, diary_day_of(now)),
    )


@router.get("/notification-time")
def read_notification_time(
    parent: Annotated[Parent, Depends(require_parent)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> NotificationTime:
    """This Parent's own time. Theirs alone: there is no way here to read the other's,
    and nothing about one of them is changed by the other."""
    return the_notification_time_of(parent, clock.now())


@router.put("/notification-time")
def set_notification_time(
    chosen: AChosenTime,
    parent: Annotated[Parent, Depends(require_parent)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> NotificationTime:
    """Move this Parent's own time, and answer with the evening it counts from.

    A PUT, and idempotent: a Parent tapping save twice has said the same thing twice.
    Saving an hour that has already gone by does push the evening it counts from to
    tomorrow even when it was the hour already on record — which is the rule being
    consistent rather than an edge case: tonight's notification has not gone out, and
    what the Parent has just said is that they want to be asked at eight.
    """
    now = clock.now()
    parent.notification_time = chosen.time
    parent.notification_time_from = counts_from(now, chosen.time)
    session.commit()
    return the_notification_time_of(parent, now)
