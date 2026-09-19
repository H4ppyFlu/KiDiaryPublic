"""Tapping the evening notification, and where it lands.

The notification showed a question. If opening it drew a different one, the app would
have told a small lie in the one place a Parent cannot check — so these tests are about
the join between the two halves that were built apart: the Delivery the scheduler wrote
before it sent anything (#11), and the Prompt the Sitting opens on.

Each one runs a real scheduler pass to get a real Delivery, and then asks over HTTP the
way the app does. The pass and the app are placed on the same evening deliberately: they
are two processes with two clocks (`an_evening.FixedClock`, `set_now`), and a Diary day
that agreed by accident would prove nothing.

What a tap looks like on the wire is `GET /api/prompt?from_the_notification=true`. That
is the whole of what the phone gets to say — it never names the Prompt it wants, because
the record of what was sent is the Delivery rather than anything the phone is holding.
"""

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from an_evening import (
    AN_EVENING,
    BERLIN,
    HER_PHONE,
    APushThatIsWatched,
    Pass,
    a_subscription,
    answer_the_prompt,
    drawn_for,
    skip,
)

#: Both Parents are seeded at 20:00, so the pass at this moment delivers to both.
HALF_PAST_EIGHT = AN_EVENING

#: The morning after, which is a Diary day of its own (ADR-0004).
THE_NEXT_MORNING = datetime(2026, 5, 13, 10, 30, tzinfo=BERLIN)

pytestmark = pytest.mark.usefixtures("empty_diary", "no_evening_left_behind")


def tapped(client: TestClient) -> dict | None:
    """What the app opens on when it was opened by tapping the notification."""
    response = client.get("/api/prompt", params={"from_the_notification": "true"})
    assert response.status_code == 200, response.text
    prompt: dict | None = response.json()["prompt"]
    return prompt


def notified(
    client: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
    moment: datetime = HALF_PAST_EIGHT,
) -> str:
    """Give this Parent tonight's notification, and say what it asked them.

    Everything below starts here, because a tap without a Delivery behind it is a
    different test: the scheduler draws, records and sends, and the text it sent is the
    only thing a Parent has seen when they pick the phone up.
    """
    client.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    evening(moment, push)
    set_now(moment)
    (pushed,) = push.sent
    return pushed.notification.body


def test_tapping_the_notification_opens_the_prompt_it_showed(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """The whole ticket in one assertion: what was on the lock screen is what is on the
    screen after the tap."""
    asked = notified(mama, push, evening, set_now)

    opened = tapped(mama)

    assert opened is not None
    assert opened["text"] == asked


def test_an_ordinary_open_is_an_ordinary_draw(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """Opening the app by hand draws under the normal rules, notification or no
    notification (user story 15).

    Told apart from the tap by skipping the delivered Prompt first: a skipped Prompt is
    the last thing the draw offers and the first thing the tap goes back to, so the two
    cannot agree by chance the way two draws on a full bank would.
    """
    asked = notified(mama, push, evening, set_now)
    delivered = tapped(mama)
    assert delivered is not None and delivered["text"] == asked
    skip(mama, delivered["id"])

    ordinary = drawn_for(mama)

    assert ordinary is not None
    assert ordinary["id"] != delivered["id"]
    # And the tap still reaches it, because a Skip is a "not now" rather than a "never"
    # (ADR-0004) and the notification is the Parent coming back to it.
    assert tapped(mama) == delivered


def test_answering_the_delivered_prompt_carries_the_sitting_on(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """After the first Prompt the notification has had its say: answering draws the next
    one under the ordinary rules, in the same response, as it does every other time."""
    notified(mama, push, evening, set_now)
    delivered = tapped(mama)
    assert delivered is not None

    response = mama.post(
        "/api/answers",
        json={"prompt_id": delivered["id"], "text": "Er hat heute die Tür selbst aufgemacht."},
    )

    assert response.status_code == 201, response.text
    next_prompt = response.json()["prompt"]
    assert next_prompt is not None
    assert next_prompt["id"] != delivered["id"]


def test_skipping_the_delivered_prompt_carries_the_sitting_on(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """Skipping it is not turning the notification down: it keeps the Sitting going, the
    way a Skip always does."""
    notified(mama, push, evening, set_now)
    delivered = tapped(mama)
    assert delivered is not None

    next_prompt = skip(mama, delivered["id"])

    assert next_prompt is not None
    assert next_prompt["id"] != delivered["id"]


def test_a_prompt_answered_since_the_push_is_not_offered_again(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """The Parent answered it on the tablet, or answered it here and came back to the
    notification still lying on the lock screen. A Prompt answered today is never asked
    again today (ADR-0004), and that rule outranks the notification: the tap draws."""
    notified(mama, push, evening, set_now)
    delivered = tapped(mama)
    assert delivered is not None
    answer_the_prompt(mama, delivered["id"])

    opened = tapped(mama)

    assert opened is not None
    assert opened["id"] != delivered["id"]


def test_last_nights_notification_does_not_open_this_evening(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """A notification is about one evening. Tapped the next morning — the push service
    was asked to let go at 04:00, but one already on the phone stays there — it opens on
    today's Sitting rather than reopening yesterday's question.

    Yesterday's Prompt is skipped this morning so that an ordinary draw would put it
    last: getting it back would mean the Delivery had been honoured across the day
    boundary.
    """
    asked = notified(mama, push, evening, set_now)
    delivered = tapped(mama)
    assert delivered is not None and delivered["text"] == asked

    set_now(THE_NEXT_MORNING)
    skip(mama, delivered["id"])

    opened = tapped(mama)

    assert opened is not None
    assert opened["id"] != delivered["id"]


def test_a_notification_belongs_to_the_parent_it_was_sent_to(
    mama: TestClient,
    papa: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """A Delivery is one Parent's evening. The other one — whose own notification never
    went out, because their phone is not subscribed — opens on a draw of their own.

    Told apart the same way as the ordinary open above: the Prompt she was asked is
    skipped on his phone, so an ordinary draw puts it last and reading her Delivery
    across would put it first.
    """
    asked = notified(mama, push, evening, set_now)
    hers = tapped(mama)
    assert hers is not None and hers["text"] == asked
    skip(papa, hers["id"])

    his = tapped(papa)

    assert his is not None
    assert his["id"] != hers["id"]
