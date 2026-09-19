"""Driving one evening over HTTP, the way a phone does.

Answering and skipping are two lines each, and both `test_sitting` and `test_skipping`
spend the whole file doing them, so they are said once here. Each helper goes through
the real endpoint and returns what the Parent would see next, because that — not the
rows behind it — is what these tests are about.

The Devices an evening reaches are here too, for the same reason: `test_push_subscriptions`
registers them and `test_the_evening_notification` sends to them, and two files naming the
same phone two different ways is how they drift apart.

So is the scheduler's own half — a clock it can be placed on and a push sender that keeps
what it was handed. `test_the_evening_notification` asserts what a pass sends;
`test_opening_the_notification` runs a pass only to have a real Delivery to tap on. The
pass itself is the `evening` fixture in `conftest.py`, because that is where fixtures are
found.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.webpush import Device, Notification, PushFailed

BERLIN = ZoneInfo("Europe/Berlin")

#: A perfectly ordinary evening, well inside one Diary day.
AN_EVENING = datetime(2026, 5, 12, 20, 30, tzinfo=BERLIN)

#: The Diary day `AN_EVENING` falls in.
THAT_DIARY_DAY = AN_EVENING.date()

#: Evenings before it, for giving a Parent a history to be drawn against. Skips and
#: Answers belong to a Diary day, so nothing done on these reaches `AN_EVENING` except
#: as the "when did this Parent last answer it" the draw sorts by.
A_FORTNIGHT_AGO = datetime(2026, 4, 28, 21, 0, tzinfo=BERLIN)
LAST_WEEK = datetime(2026, 5, 5, 21, 0, tzinfo=BERLIN)
THE_DAY_BEFORE = datetime(2026, 5, 11, 21, 0, tzinfo=BERLIN)


#: Three Devices. The endpoint is what a push service hands the browser, and it is what
#: tells one Device from another everywhere below.
HER_PHONE = "https://push.example.test/subscriptions/aaa111"
HER_TABLET = "https://push.example.test/subscriptions/bbb222"
HIS_PHONE = "https://push.example.test/subscriptions/ccc333"


def a_subscription(endpoint: str, p256dh: str = "a-public-key", auth: str = "a-secret") -> dict:
    """What `PushSubscription.toJSON()` gives a browser, `expirationTime` included — the
    app posts that object whole, so the tests post the same shape."""
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": p256dh, "auth": auth}}


def drawn_for(client: TestClient) -> dict | None:
    """Whatever this Parent is being asked right now."""
    return client.get("/api/prompt").json()["prompt"]


def answer(client: TestClient, text: str = "Etwas, das bleiben soll.") -> dict:
    """Answer whatever is in front of this Parent, and return the draw that follows."""
    prompt = drawn_for(client)
    assert prompt is not None, "nothing was drawn to answer"
    response = client.post("/api/answers", json={"prompt_id": prompt["id"], "text": text})
    assert response.status_code == 201, response.text
    return {"answered": prompt, "next": response.json()["prompt"]}


def skip(client: TestClient, prompt_id: int) -> dict | None:
    """Pass over a Prompt, and return the Prompt drawn in its place."""
    response = client.post("/api/skips", json={"prompt_id": prompt_id})
    assert response.status_code == 201, response.text
    return response.json()["prompt"]


def answer_the_prompt(client: TestClient, prompt_id: int, text: str = "Damals.") -> None:
    """Answer one named Prompt rather than whichever was drawn.

    A phone only ever answers what it was asked, so this is not a Parent's path through
    the app — but it is the same endpoint, and naming the Prompt is what lets a test
    build a history exact enough to assert the draw order against.
    """
    response = client.post("/api/answers", json={"prompt_id": prompt_id, "text": text})
    assert response.status_code == 201, response.text


def the_whole_bank(client: TestClient) -> list[int]:
    """Every Prompt id, learned by skipping the bank once on the evening you are on.

    Skipping rather than answering, because a Skip expires with its Diary day while an
    Answer is the history the draw order is made of: a bank learned on a setup evening
    leaves the evening under test with a clean slate.
    """
    learned: list[int] = []
    while (prompt := drawn_for(client)) is not None and prompt["id"] not in learned:
        learned.append(prompt["id"])
        skip(client, prompt["id"])
    return learned


def with_one_prompt_answered_longest_ago(
    client: TestClient, set_now: Callable[[datetime], None]
) -> int:
    """Give this Parent a history in which exactly one Prompt stands out, and name it.

    Every Prompt is answered a fortnight ago and all but one again the day before, so
    the least-recently-answered rule has a single right answer and the draw is left with
    no freedom at all — which is what lets a test assert one Prompt rather than a
    distribution. Returns that Prompt's id, and leaves the Parent on `THE_DAY_BEFORE`.
    """
    set_now(A_FORTNIGHT_AGO)
    bank = the_whole_bank(client)
    longest_ago, *the_rest = bank
    for prompt_id in bank:
        answer_the_prompt(client, prompt_id)

    set_now(THE_DAY_BEFORE)
    for prompt_id in the_rest:
        answer_the_prompt(client, prompt_id)

    return longest_ago


class FixedClock:
    """The scheduler's own clock. It has one of its own rather than the API's, because
    it is a separate process — a test moves the two independently, and the difference
    between them is how "the app at nine, the pass at ten" is written."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


@dataclass
class Pushed:
    endpoint: str
    notification: Notification


class APushThatIsWatched:
    """A push sender that keeps what it was handed, and refuses what it is told to.

    Refusing by endpoint is how a phone whose push service is down is written: the send
    fails for that Device and for nothing else. `gone` is the other refusal — the one
    that says the subscription itself is finished.
    """

    def __init__(self, refusing: set[str] | None = None, gone: set[str] | None = None) -> None:
        self.sent: list[Pushed] = []
        self.refusing = refusing or set()
        self.gone = gone or set()

    def send(self, device: Device, notification: Notification) -> None:
        if device.endpoint in self.gone:
            raise PushFailed("The push service refused it: 410", status=410)
        if device.endpoint in self.refusing:
            raise PushFailed("The push service refused it: 500", status=500)
        self.sent.append(Pushed(device.endpoint, notification))

    def endpoints(self) -> list[str]:
        return [push.endpoint for push in self.sent]

    def bodies(self) -> list[str]:
        return [push.notification.body for push in self.sent]


#: One pass of the scheduler, at a moment and with a sender of the test's choosing.
Pass = Callable[[datetime, APushThatIsWatched], None]
