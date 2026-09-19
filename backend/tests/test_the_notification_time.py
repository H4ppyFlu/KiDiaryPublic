"""Each Parent's own notification time: reading it, moving it, and being asked at it.

Two Parents, two evenings. One shared hour would land in the middle of one of the two
bedtimes (user stories 24 and 25), so the time is a column on `parents` rather than
configuration, and the device asking is the one that says whose it is — there is no way
here to read or move the other Parent's.

The rule worth the tests is what a time of day does *not* say: which evening it is for.
Typed at nine, "20:00" is somebody setting a bedtime for tomorrow and not asking to be
notified within the minute, so an hour that has already gone by counts from the next
Diary day (`app/notification_time.py`). An hour still ahead counts tonight.

The last two tests carry that all the way through to a real scheduler pass, because that
is where it is finally either true or not: what the endpoint wrote is only worth
anything if the process that wakes the house up reads it the same way.
"""

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from an_evening import BERLIN, HER_PHONE, HIS_PHONE, APushThatIsWatched, Pass, a_subscription
from app.models import Delivery

#: Before either Parent's seeded 20:00, on an ordinary Diary day.
SEVEN_O_CLOCK = datetime(2026, 5, 12, 19, 0, tzinfo=BERLIN)

#: After it, on the same Diary day. Where "already gone by" is decided.
NINE_O_CLOCK = datetime(2026, 5, 12, 21, 0, tzinfo=BERLIN)

#: The Diary day after that one, at eight in the evening.
TOMORROW_AT_EIGHT = datetime(2026, 5, 13, 20, 0, tzinfo=BERLIN)

pytestmark = pytest.mark.usefixtures(
    "empty_diary", "no_evening_left_behind", "notification_times_as_seeded"
)


def the_time(client: TestClient) -> dict:
    response = client.get("/api/notification-time")
    assert response.status_code == 200, response.text
    answer: dict = response.json()
    return answer


def move_to(client: TestClient, at: str) -> dict:
    response = client.put("/api/notification-time", json={"time": at})
    assert response.status_code == 200, response.text
    answer: dict = response.json()
    return answer


def test_a_parent_sees_the_hour_they_are_asked_at(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The seeded 20:00, and it counts tonight: nothing has been moved."""
    set_now(SEVEN_O_CLOCK)

    assert the_time(mama) == {"time": "20:00", "counts_tonight": True}


def test_a_parent_moves_their_own_hour(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(SEVEN_O_CLOCK)

    moved = move_to(mama, "21:30")

    assert moved == {"time": "21:30", "counts_tonight": True}
    # And it is the app's answer from then on, not only this response.
    assert the_time(mama) == {"time": "21:30", "counts_tonight": True}


def test_one_parents_hour_says_nothing_about_the_others(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The point of the whole setting. Two Parents, two evenings, two bedtimes."""
    set_now(SEVEN_O_CLOCK)

    move_to(mama, "22:15")

    assert the_time(mama)["time"] == "22:15"
    assert the_time(papa)["time"] == "20:00"


def test_an_hour_that_has_gone_by_is_a_request_for_tomorrow(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Nine in the evening, and she says eight. She is not asking to be notified now;
    she is saying when her evenings start. The screen is told so in the same breath,
    because a Parent left to wait for it tonight would think it broken."""
    set_now(NINE_O_CLOCK)

    moved = move_to(mama, "20:00")

    assert moved == {"time": "20:00", "counts_tonight": False}


def test_an_hour_still_to_come_is_for_tonight(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The other half of the same rule, and the ordinary case: at nine, "22:00" is a
    Parent asking to be asked in an hour."""
    set_now(NINE_O_CLOCK)

    assert move_to(mama, "22:00") == {"time": "22:00", "counts_tonight": True}


def test_tomorrow_arrives(mama: TestClient, set_now: Callable[[datetime], None]) -> None:
    """The evening an hour was set too late for passes, and the hour is simply the
    Parent's hour again."""
    set_now(NINE_O_CLOCK)
    move_to(mama, "20:00")

    set_now(TOMORROW_AT_EIGHT)

    assert the_time(mama) == {"time": "20:00", "counts_tonight": True}


def test_an_hour_is_kept_to_the_minute(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The pass runs once a minute, so seconds are a resolution nothing could honour."""
    set_now(SEVEN_O_CLOCK)

    assert move_to(mama, "21:30:45")["time"] == "21:30"


def test_an_hour_with_an_offset_is_refused(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """A notification time is local time, like a Diary day. A phone in another timezone
    saying 20:00+09:00 would be asking a question this app has no answer to."""
    set_now(SEVEN_O_CLOCK)

    response = mama.put("/api/notification-time", json={"time": "20:00+09:00"})

    assert response.status_code == 422, response.text
    assert the_time(mama)["time"] == "20:00"


def test_a_device_that_has_not_said_who_holds_it_has_no_hour(client: TestClient) -> None:
    """The time belongs to a Parent, so a device with the PIN and nothing else is asked
    the question it is actually missing rather than for the PIN again (ADR-0010)."""
    assert client.get("/api/notification-time").status_code == 403
    assert client.put("/api/notification-time", json={"time": "21:00"}).status_code == 403


def test_the_scheduler_honours_a_new_hour_on_the_next_diary_day(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """The whole rule, end to end and across two processes: she says eight at nine, and
    is asked at eight — tomorrow."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    set_now(NINE_O_CLOCK)
    move_to(mama, "20:00")

    # Tonight the hour is past, and the pass leaves her alone anyway.
    evening(NINE_O_CLOCK, push)
    assert push.sent == []
    assert deliveries() == []

    # Tomorrow it is her hour, and nothing about it is special any more.
    evening(TOMORROW_AT_EIGHT, push)

    assert push.endpoints() == [HER_PHONE]
    assert [row.diary_day for row in deliveries()] == [TOMORROW_AT_EIGHT.date()]


def test_the_scheduler_honours_a_new_hour_the_same_evening(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """And the other half: an hour still to come is tonight's, at the minute it names
    and not before."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    set_now(SEVEN_O_CLOCK)
    move_to(mama, "22:00")

    evening(NINE_O_CLOCK, push)
    assert push.sent == []

    evening(datetime(2026, 5, 12, 22, 0, tzinfo=BERLIN), push)

    assert push.endpoints() == [HER_PHONE]


def test_the_other_parent_is_untouched_by_a_move(
    mama: TestClient,
    papa: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
    parent_ids: dict[int, int],
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """She pushes her evening past his. His arrives at eight as it always did."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))
    set_now(SEVEN_O_CLOCK)
    move_to(mama, "22:00")

    evening(datetime(2026, 5, 12, 20, 30, tzinfo=BERLIN), push)

    assert [row.parent_id for row in deliveries()] == [parent_ids[2]]
