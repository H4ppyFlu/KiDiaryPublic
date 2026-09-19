"""Which of the two Parents a device belongs to.

The PIN is shared (ADR-0005), so it says nothing about who is holding the phone. A
signed-in device says that for itself, once, and the cookie comes back carrying the
answer (ADR-0010). These tests are about that second step: what a device may do before
it, what it may do after, and what survives a restart of the Pi.
"""

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.config import Settings
from app.main import create_app


def test_the_pin_alone_leaves_a_device_without_a_parent(client: TestClient) -> None:
    """The state between the two screens: signed in, and nobody in particular."""
    assert client.get("/api/session").json() == {"parent": None}


def test_a_device_without_a_parent_is_shown_both_names_to_choose_between(
    client: TestClient,
) -> None:
    """The one thing it needs before it can answer the question, and it is behind the
    PIN like everything else."""
    parents = client.get("/api/parents").json()

    assert [parent["name"] for parent in parents] == ["Mama", "Papa"]
    assert [parent["position"] for parent in parents] == [1, 2]


def test_a_device_without_a_parent_cannot_write_an_answer(client: TestClient) -> None:
    """403 rather than 401: it holds the PIN, so sending it back to the PIN screen
    would ask it for something it has already given."""
    drawn = client.get("/api/prompt")
    assert drawn.status_code == 403

    written = client.post("/api/answers", json={"prompt_id": 1, "text": "Ohne Namen."})
    assert written.status_code == 403


def test_choosing_a_parent_is_what_the_session_reports_afterwards(mama: TestClient) -> None:
    body = mama.get("/api/session").json()

    assert body["parent"]["name"] == "Mama"
    assert body["parent"]["position"] == 1


def test_the_claim_rides_in_the_cookie_and_survives_a_restart(
    mama: TestClient, settings: Settings
) -> None:
    """Nothing is kept server-side, so a rebooted Pi still knows whose phone this is."""
    after_a_restart = TestClient(create_app(settings))
    after_a_restart.cookies.set(COOKIE_NAME, mama.cookies[COOKIE_NAME])

    assert after_a_restart.get("/api/session").json()["parent"]["name"] == "Mama"


def test_a_device_can_say_it_is_the_other_parent_instead(
    mama: TestClient, client: TestClient
) -> None:
    """A replacement rather than an addition. There is no button for it in the app —
    the phones are personal — but the claim is a claim, and it can be restated."""
    papa_id = next(p["id"] for p in client.get("/api/parents").json() if p["position"] == 2)

    assert mama.put("/api/session/parent", json={"parent_id": papa_id}).status_code == 204

    assert mama.get("/api/session").json()["parent"]["name"] == "Papa"


def test_a_parent_who_is_not_seeded_cannot_be_claimed(mama: TestClient) -> None:
    """And the refusal leaves the claim the device already had standing."""
    assert mama.put("/api/session/parent", json={"parent_id": 9999}).status_code == 404

    assert mama.get("/api/session").json()["parent"]["name"] == "Mama"


def test_a_cookie_naming_a_parent_is_still_only_accepted_when_signed(
    mama: TestClient, signed_out_client: TestClient, settings: Settings
) -> None:
    """The Parent is a claim, but the cookie carrying it is not writable by hand."""
    signed_out_client.cookies.set(COOKIE_NAME, "signed-in:1")
    assert signed_out_client.get("/api/session").status_code == 401

    stranger = TestClient(create_app(settings.model_copy(update={"session_secret": "elsewhere"})))
    stranger.post("/api/session", json={"pin": settings.pin})
    stranger.put("/api/session/parent", json={"parent_id": 1})
    signed_out_client.cookies.set(COOKIE_NAME, stranger.cookies[COOKIE_NAME])

    assert signed_out_client.get("/api/session").status_code == 401
