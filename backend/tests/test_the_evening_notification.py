"""The evening pass: one notification per Parent per Diary day, carrying a real Prompt.

These tests drive `send_what_is_due` directly rather than over HTTP, because the
scheduler has no HTTP surface — it is its own Compose service with its own command
(ADR-0009), and what it does happens at a time nobody is looking. The Devices it sends
to are registered through the real endpoint, though, so a test never puts a
subscription in the table by a route a phone could not take.

The push itself is a fake here. What the real one puts on the wire is held to RFC
8291's published example in `test_web_push.py`; what matters below is *how many* times
it is called, and with which Prompt.

The restart these tests simulate is the point of the whole design: the Delivery is
recorded before the push goes out, so a scheduler that dies mid-evening and comes back
sends nothing a second time. A Parent woken twice by the same question has been let
down worse than one woken not at all.
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from an_evening import (
    AN_EVENING,
    HER_PHONE,
    HER_TABLET,
    HIS_PHONE,
    THAT_DIARY_DAY,
    APushThatIsWatched,
    Pass,
    a_subscription,
    answer_the_prompt,
    the_whole_bank,
)
from app.models import Delivery, Prompt, PushSubscription
from app.seed import PROMPT_BANK

BERLIN = ZoneInfo("Europe/Berlin")

#: Both Parents are seeded at 20:00, so this is after one and the evening is well
#: inside `THAT_DIARY_DAY`.
HALF_PAST_EIGHT = AN_EVENING

#: Before either Parent's time, on the same Diary day.
SEVEN_O_CLOCK = datetime(2026, 5, 12, 19, 0, tzinfo=BERLIN)


pytestmark = pytest.mark.usefixtures("empty_diary", "no_evening_left_behind")


def test_each_parent_is_sent_one_prompt_when_their_evening_comes(
    mama: TestClient,
    papa: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    parent_ids: dict[int, int],
) -> None:
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))

    evening(HALF_PAST_EIGHT, push)

    assert sorted(push.endpoints()) == sorted([HER_PHONE, HIS_PHONE])
    # A real question, not a placeholder: this is the whole reason the Prompt is drawn
    # before the notification goes out rather than when the app is opened.
    assert all(body in PROMPT_BANK for body in push.bodies())
    assert [(row.parent_id, row.diary_day) for row in deliveries()] == [
        (parent_ids[1], THAT_DIARY_DAY),
        (parent_ids[2], THAT_DIARY_DAY),
    ]


def test_nothing_is_sent_before_the_configured_time(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """The pass runs every minute all day. Almost every one of them has nothing to do,
    and doing nothing has to leave nothing behind — a Delivery written early would
    silence the evening it was meant to announce."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(SEVEN_O_CLOCK, push)

    assert push.sent == []
    assert deliveries() == []


def test_each_parent_is_sent_at_their_own_time(
    mama: TestClient,
    papa: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    notification_time: Callable[[int, time], None],
) -> None:
    """One shared hour would land in the middle of one of the two bedtimes. At half
    past eight the one who asked for nine is not disturbed."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))
    notification_time(2, time(21, 0))

    evening(HALF_PAST_EIGHT, push)

    assert push.endpoints() == [HER_PHONE]


def test_a_pass_that_runs_again_the_same_evening_sends_nothing(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """The pass runs every minute, so this is the ordinary case rather than the odd
    one: 20:00 is due, and so is every minute until 04:00."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT, push)
    evening(HALF_PAST_EIGHT + timedelta(minutes=1), push)
    evening(HALF_PAST_EIGHT + timedelta(hours=2), push)

    assert push.endpoints() == [HER_PHONE]
    assert len(deliveries()) == 1


def test_a_notification_is_recorded_before_it_is_sent(
    mama: TestClient,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """The order that survives a restart. A send that never happened leaves the record
    behind anyway, and the restart after it stays quiet — at most one notification per
    evening, and a lost one is the price of never sending two."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    the_push_service_was_down = APushThatIsWatched(refusing={HER_PHONE})

    evening(HALF_PAST_EIGHT, the_push_service_was_down)

    (recorded,) = deliveries()
    assert recorded.prompt_id is not None
    # Nothing reached a phone, and the row says so rather than claiming it did.
    assert recorded.sent_at is None

    after_a_restart = APushThatIsWatched()
    evening(HALF_PAST_EIGHT + timedelta(minutes=1), after_a_restart)

    assert after_a_restart.sent == []


def test_the_delivery_records_the_prompt_that_was_pushed(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    session: Session,
) -> None:
    """What #12 opens the app on: tapping the notification has to reach the Prompt the
    notification showed, and this row is the only thing that remembers which it was."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT, push)

    (recorded,) = deliveries()
    (pushed,) = push.sent
    recorded_prompt = session.get(Prompt, recorded.prompt_id)
    assert recorded_prompt is not None
    assert pushed.notification.body == recorded_prompt.text
    assert recorded.sent_at is not None


def test_the_next_diary_day_is_a_new_notification(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT, push)
    evening(HALF_PAST_EIGHT + timedelta(days=1), push)

    assert push.endpoints() == [HER_PHONE, HER_PHONE]
    assert [row.diary_day for row in deliveries()] == [
        THAT_DIARY_DAY,
        THAT_DIARY_DAY + timedelta(days=1),
    ]


def test_every_device_a_parent_carries_is_notified_with_the_same_prompt(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """A Parent with a phone and a tablet has one evening, not two: both are told, and
    both are told the same question."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    mama.put("/api/push/subscription", json=a_subscription(HER_TABLET))

    evening(HALF_PAST_EIGHT, push)

    assert sorted(push.endpoints()) == sorted([HER_PHONE, HER_TABLET])
    assert len(set(push.bodies())) == 1
    assert len(deliveries()) == 1


def test_one_parents_push_failing_leaves_the_others_evening_alone(
    mama: TestClient,
    papa: TestClient,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    parent_ids: dict[int, int],
) -> None:
    """Two Parents, two push services, and one of them is having a bad night."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))
    one_service_is_down = APushThatIsWatched(refusing={HER_PHONE})

    evening(HALF_PAST_EIGHT, one_service_is_down)

    assert one_service_is_down.endpoints() == [HIS_PHONE]
    by_parent = {row.parent_id: row for row in deliveries()}
    assert by_parent[parent_ids[1]].sent_at is None
    assert by_parent[parent_ids[2]].sent_at is not None


def test_one_device_failing_does_not_cost_the_parents_other_device(
    mama: TestClient,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """A tablet that has been switched off for a month must not silence the phone in
    the Parent's hand."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    mama.put("/api/push/subscription", json=a_subscription(HER_TABLET))
    the_tablet_is_gone = APushThatIsWatched(refusing={HER_TABLET})

    evening(HALF_PAST_EIGHT, the_tablet_is_gone)

    assert the_tablet_is_gone.endpoints() == [HER_PHONE]
    (recorded,) = deliveries()
    assert recorded.sent_at is not None


def test_a_subscription_the_push_service_has_forgotten_is_dropped(
    mama: TestClient,
    evening: Pass,
    registered: Callable[[], list[PushSubscription]],
) -> None:
    """410 is the one refusal that is about the row rather than the request: nothing
    will ever reach that endpoint again. Keeping it would mean pushing at it every
    evening for years, and it would read like a Parent who has notifications on."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    mama.put("/api/push/subscription", json=a_subscription(HER_TABLET))
    the_tablet_is_gone = APushThatIsWatched(gone={HER_TABLET})

    evening(HALF_PAST_EIGHT, the_tablet_is_gone)

    assert [row.endpoint for row in registered()] == [HER_PHONE]


def test_a_device_that_is_only_unreachable_keeps_its_subscription(
    mama: TestClient,
    evening: Pass,
    registered: Callable[[], list[PushSubscription]],
) -> None:
    """The other side of the test above, and the more important one: a push service
    having a bad night must not cost a Parent the phone in their hand."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    the_service_is_down = APushThatIsWatched(refusing={HER_PHONE})

    evening(HALF_PAST_EIGHT, the_service_is_down)

    assert [row.endpoint for row in registered()] == [HER_PHONE]


def test_a_parent_with_no_device_is_not_recorded_as_delivered(
    mama: TestClient,
    papa: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    parent_ids: dict[int, int],
) -> None:
    """Switching a phone on at half past nine is a Parent asking for tonight's
    notification, and they get it. A Delivery written for a Parent with nothing to send
    to would have spent their evening on nobody."""
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))

    evening(HALF_PAST_EIGHT, push)
    assert [row.parent_id for row in deliveries()] == [parent_ids[2]]

    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    evening(HALF_PAST_EIGHT + timedelta(hours=1), push)

    assert sorted(push.endpoints()) == sorted([HIS_PHONE, HER_PHONE])


def test_the_prompt_is_drawn_by_the_rules_the_app_draws_by(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    set_now: Callable[[datetime], None],
) -> None:
    """A notification carrying a Prompt the Sitting would not have offered is a
    notification that lies. Every Prompt but one is answered tonight, so ADR-0004's
    filter leaves the draw no freedom at all and the Prompt pushed is that one."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    set_now(HALF_PAST_EIGHT)
    bank = the_whole_bank(mama)
    the_one_left, *the_rest = bank
    for prompt_id in the_rest:
        answer_the_prompt(mama, prompt_id)

    evening(HALF_PAST_EIGHT, push)

    (pushed,) = push.sent
    assert pushed.notification.body == _prompt_text_by_id(mama, the_one_left)


def _prompt_text_by_id(client: TestClient, prompt_id: int) -> str:
    """The text of a Prompt, from the only place the API offers it: a draw."""
    drawn = client.get("/api/prompt").json()["prompt"]
    assert drawn is not None and drawn["id"] == prompt_id
    return drawn["text"]


def test_a_diary_day_already_answered_out_is_not_notified_about(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    set_now: Callable[[datetime], None],
) -> None:
    """A Parent who worked through the whole bank before eight has nothing left to be
    asked, and the evening passes without waking them."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    set_now(SEVEN_O_CLOCK)
    for prompt_id in the_whole_bank(mama):
        answer_the_prompt(mama, prompt_id)

    evening(HALF_PAST_EIGHT, push)

    assert push.sent == []
    assert deliveries() == []


def test_the_notification_expires_with_its_diary_day(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
) -> None:
    """A push service holds a notification for a phone that is off. This one asks it to
    let go at 04:00, when the Diary day it is about gives way to the next: a question
    about today, arriving tomorrow, is a question that has outlived itself."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT, push)

    (pushed,) = push.sent
    # 20:30 to 04:00 is seven and a half hours.
    assert pushed.notification.expires_in == timedelta(hours=7, minutes=30)


def test_a_notification_says_which_app_woke_them(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
) -> None:
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT, push)

    (pushed,) = push.sent
    assert pushed.notification.title == "Kidiary"


def test_a_diary_day_is_the_one_that_is_running_at_one_in_the_morning(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """01:30 still belongs to the evening that just ended (ADR-0004), so a scheduler
    that was down all evening and came back at one o'clock sends yesterday's
    notification rather than starting a new day early."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(datetime(2026, 5, 13, 1, 30, tzinfo=BERLIN), push)

    assert [row.diary_day for row in deliveries()] == [THAT_DIARY_DAY]


def test_the_pass_is_indifferent_to_the_order_of_the_parents(
    mama: TestClient,
    papa: TestClient,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
    parent_ids: dict[int, int],
) -> None:
    """A failure that reached the loop rather than one send would stop after the first
    Parent. This is the same assertion as the failing-push test from the other side:
    the first Parent failing must not cost the second theirs."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    papa.put("/api/push/subscription", json=a_subscription(HIS_PHONE))
    every_service_is_down = APushThatIsWatched(refusing={HER_PHONE, HIS_PHONE})

    evening(HALF_PAST_EIGHT, every_service_is_down)

    assert sorted(row.parent_id for row in deliveries()) == sorted(parent_ids.values())


def test_a_diary_day_the_scheduler_missed_is_not_caught_up_later(
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """A Pi that was off for three days comes back to one evening, not four. Yesterday's
    question is about yesterday, and nobody wants to be asked it now."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    evening(HALF_PAST_EIGHT + timedelta(days=3), push)

    assert [row.diary_day for row in deliveries()] == [THAT_DIARY_DAY + timedelta(days=3)]
    assert len(push.sent) == 1


def test_a_delivery_is_dated_by_the_diary_day_and_not_by_the_clock(
    session: Session,
    mama: TestClient,
    push: APushThatIsWatched,
    evening: Pass,
    deliveries: Callable[[], list[Delivery]],
) -> None:
    """The same assertion as the 01:30 test, made about the row rather than the send —
    `sent_at` is the moment, `diary_day` is the evening, and they are two different
    things after midnight."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    after_midnight = datetime(2026, 5, 13, 1, 30, tzinfo=BERLIN)

    evening(after_midnight, push)

    (recorded,) = deliveries()
    assert recorded.diary_day == THAT_DIARY_DAY
    assert recorded.sent_at is not None
    assert recorded.sent_at.astimezone(BERLIN).date() == date(2026, 5, 13)
