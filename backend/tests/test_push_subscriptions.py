"""Registering one device for the evening notification.

A Parent turns notifications on for the phone in their hand, and from then on that
phone is a row the evening scheduler can send to. The browser half — the permission prompt, the
subscription itself — is the phone's business; what is asserted here is what the API
does with what the phone hands it.

Subscriptions have no read endpoint: the only thing that reads them is the scheduler,
which is a separate process with no HTTP of its own (`test_the_evening_notification`).
So unlike the Sitting and the Diary, these tests look at the rows, the way
`test_seed.py` does for the Prompt bank.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from an_evening import HER_PHONE, HER_TABLET, a_subscription
from app.config import Settings
from app.main import create_app
from app.models import Parent, PushSubscription
from app.vapid import generate


@pytest.fixture(autouse=True)
def no_subscriptions_left_behind(session: Session) -> Iterator[None]:
    """The database is built once for the whole run, so a test that registers a device
    has to forget it again or the next one inherits a phone it never had."""
    yield
    session.query(PushSubscription).delete()
    session.commit()


@pytest.fixture
def parent_ids(session: Session) -> dict[int, int]:
    """The two seeded Parents' ids, by position, for asserting who a row belongs to."""
    return {parent.position: parent.id for parent in session.scalars(select(Parent))}


def test_the_browser_is_given_the_public_key(client: TestClient, settings: Settings) -> None:
    """A browser cannot subscribe without it, and it has nowhere else to get it."""
    response = client.get("/api/push/key")

    assert response.status_code == 200
    assert response.json() == {"public_key": settings.vapid_public_key}


def test_a_granted_subscription_is_stored_against_the_parent(
    mama: TestClient,
    registered: Callable[[], list[PushSubscription]],
    parent_ids: dict[int, int],
) -> None:
    response = mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    assert response.status_code == 204, response.text
    (stored,) = registered()
    assert stored.parent_id == parent_ids[1]
    assert stored.endpoint == HER_PHONE
    assert (stored.p256dh_key, stored.auth_key) == ("a-public-key", "a-secret")


def test_re_registering_the_same_device_updates_rather_than_duplicates(
    mama: TestClient, registered: Callable[[], list[PushSubscription]]
) -> None:
    """The app registers whenever it opens with permission already granted, not only
    when the button is tapped, so this is the ordinary path rather than the odd one —
    and a browser that re-subscribed brings new keys with it."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    again = mama.put(
        "/api/push/subscription",
        json=a_subscription(HER_PHONE, p256dh="a-newer-public-key", auth="a-newer-secret"),
    )

    assert again.status_code == 204, again.text
    (stored,) = registered()
    assert (stored.p256dh_key, stored.auth_key) == ("a-newer-public-key", "a-newer-secret")


def test_each_device_a_parent_carries_is_its_own_row(
    mama: TestClient,
    registered: Callable[[], list[PushSubscription]],
    parent_ids: dict[int, int],
) -> None:
    """One row per device, so an evening reaches the phone in the pocket and the
    tablet on the shelf both."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    mama.put("/api/push/subscription", json=a_subscription(HER_TABLET))

    assert [(row.parent_id, row.endpoint) for row in registered()] == [
        (parent_ids[1], HER_PHONE),
        (parent_ids[1], HER_TABLET),
    ]


def test_a_device_that_changes_hands_moves_to_the_other_parent(
    mama: TestClient,
    papa: TestClient,
    registered: Callable[[], list[PushSubscription]],
    parent_ids: dict[int, int],
) -> None:
    """The endpoint names a device, and a device belongs to one Parent (ADR-0010).
    Re-registering it under the other one moves the row rather than doubling it — the
    first Parent must not keep getting notifications on a phone they no longer hold."""
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    papa.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    (stored,) = registered()
    assert stored.parent_id == parent_ids[2]


def test_turning_notifications_off_forgets_that_device_only(
    mama: TestClient, registered: Callable[[], list[PushSubscription]]
) -> None:
    mama.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    mama.put("/api/push/subscription", json=a_subscription(HER_TABLET))

    off = mama.request("DELETE", "/api/push/subscription", json={"endpoint": HER_PHONE})

    assert off.status_code == 204, off.text
    assert [row.endpoint for row in registered()] == [HER_TABLET]


def test_turning_off_a_device_that_was_never_on_is_not_an_error(mama: TestClient) -> None:
    """A phone that unsubscribed while the Pi was unreachable says so again later, and
    gets the same answer: there is nothing here to send to it."""
    off = mama.request("DELETE", "/api/push/subscription", json={"endpoint": HER_PHONE})

    assert off.status_code == 204, off.text


def test_a_device_that_has_not_said_which_parent_it_is_cannot_register(
    client: TestClient, registered: Callable[[], list[PushSubscription]]
) -> None:
    """403 rather than 401: the device has the PIN, it has only not answered "wer
    schreibt?" yet — and a subscription belongs to one of the two Parents."""
    response = client.put("/api/push/subscription", json=a_subscription(HER_PHONE))

    assert response.status_code == 403
    assert registered() == []


def test_a_signed_out_device_is_refused_all_of_it(signed_out_client: TestClient) -> None:
    assert signed_out_client.get("/api/push/key").status_code == 401
    refused = signed_out_client.put("/api/push/subscription", json=a_subscription(HER_PHONE))
    assert refused.status_code == 401


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"endpoint": "", "keys": {"p256dh": "a", "auth": "b"}}, id="no endpoint"),
        pytest.param(
            {"endpoint": "http://push.example.test/x", "keys": {"p256dh": "a", "auth": "b"}},
            id="not https",
        ),
        pytest.param({"endpoint": HER_PHONE, "keys": {"p256dh": "", "auth": "b"}}, id="no p256dh"),
        pytest.param({"endpoint": HER_PHONE}, id="no keys at all"),
    ],
)
def test_a_subscription_that_could_never_be_pushed_to_is_refused(
    mama: TestClient, broken: dict, registered: Callable[[], list[PushSubscription]]
) -> None:
    """The scheduler sends from this table. A row that cannot be sent to is worse in it
    than a missing one, because it reads as a Parent who has notifications on."""
    response = mama.put("/api/push/subscription", json=broken)

    assert response.status_code == 422
    assert registered() == []


class TestAStackWithoutVapidKeys:
    """A Pi that has never had keys put in its `.env`. It runs — everything but the
    notification works — and it says plainly that it cannot offer this one."""

    @pytest.fixture
    def api_without_keys(self, settings: Settings) -> FastAPI:
        return create_app(
            settings.model_copy(update={"vapid_public_key": "", "vapid_private_key": ""})
        )

    @pytest.fixture
    def phone(self, api_without_keys: FastAPI, settings: Settings) -> Iterator[TestClient]:
        with TestClient(api_without_keys) as device:
            assert device.post("/api/session", json={"pin": settings.pin}).status_code == 204
            parents = device.get("/api/parents").json()
            claimed = device.put("/api/session/parent", json={"parent_id": parents[0]["id"]})
            assert claimed.status_code == 204
            yield device

    def test_there_is_no_public_key_to_subscribe_with(self, phone: TestClient) -> None:
        assert phone.get("/api/push/key").json() == {"public_key": None}

    def test_registering_is_refused_rather_than_quietly_stored(self, phone: TestClient) -> None:
        """A row nothing can ever send to would read as a Parent who has notifications
        on. 503, because what is missing belongs to the deployment, not the request."""
        response = phone.put("/api/push/subscription", json=a_subscription(HER_PHONE))

        assert response.status_code == 503


class TestKeysThatCannotWork:
    """A mis-paste in `.env` stops the container rather than one phone. The alternative
    is a Parent spending their one permission prompt on a subscription that is refused
    months later, and on iOS there is no second prompt without reinstalling the app."""

    def test_half_a_pair_refuses_to_start(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="two halves"):
            create_app(settings.model_copy(update={"vapid_private_key": ""}))

    def test_a_truncated_key_refuses_to_start(self, settings: Settings) -> None:
        half_a_key = settings.vapid_public_key[:40]

        with pytest.raises(ValueError, match="bytes rather than"):
            create_app(settings.model_copy(update={"vapid_public_key": half_a_key}))

    def test_two_keys_that_are_not_halves_of_each_other_refuse_to_start(
        self, settings: Settings
    ) -> None:
        """The quiet one: both keys are valid, so nothing below this would notice. It
        is what a pair replaced only halfway looks like."""
        another_public_key, _ = generate()

        with pytest.raises(ValueError, match="not the public half"):
            create_app(settings.model_copy(update={"vapid_public_key": another_public_key}))
