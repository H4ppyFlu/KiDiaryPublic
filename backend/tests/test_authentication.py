"""The shared PIN, and the year-long cookie it buys.

Only devices already on the family tailnet can reach the app at all (ADR-0005), so
these tests are about the second lock rather than the first: a phone someone picks up
must not open onto the Diary, and neither Parent may be asked to type anything on the
way to a five-second Answer.
"""

from fastapi.testclient import TestClient

from app.auth import COOKIE_MAX_AGE, COOKIE_NAME
from app.config import Settings
from app.main import create_app

#: The one thing a device without the cookie is allowed to ask for.
THE_EXCHANGE = ("post", "/api/session")


def test_the_right_pin_buys_a_cookie_that_lasts_a_year(
    signed_out_client: TestClient, settings: Settings
) -> None:
    assert COOKIE_MAX_AGE == 365 * 24 * 60 * 60

    response = signed_out_client.post("/api/session", json={"pin": settings.pin})

    assert response.status_code == 204
    assert signed_out_client.cookies.get(COOKIE_NAME) is not None

    # A year, and unreadable to scripts: the frontend never needs to see it, the
    # browser only needs to send it.
    set_cookie = response.headers["set-cookie"].lower()
    assert f"max-age={COOKIE_MAX_AGE}" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    # And it is what the API accepts afterwards — as a device that has the PIN but
    # has not yet said which Parent is holding it.
    session = signed_out_client.get("/api/session")
    assert session.status_code == 200
    assert session.json() == {"parent": None}


def test_the_wrong_pin_is_refused_and_leaves_the_device_signed_out(
    signed_out_client: TestClient, settings: Settings
) -> None:
    response = signed_out_client.post("/api/session", json={"pin": settings.pin + "0"})

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert signed_out_client.cookies.get(COOKIE_NAME) is None
    # And the refusal really was a refusal: the device is still shut out.
    assert signed_out_client.get("/api/child").status_code == 401


def test_every_endpoint_but_the_exchange_refuses_a_device_without_the_cookie(
    signed_out_client: TestClient,
) -> None:
    """Walked from the schema rather than listed here, so an endpoint added later
    without the guard fails this test instead of quietly opening the Diary."""
    paths: dict[str, dict[str, object]] = signed_out_client.get("/openapi.json").json()["paths"]

    guarded = [
        (method, path)
        for path, operations in paths.items()
        for method in operations
        if (method, path) != THE_EXCHANGE
    ]

    assert guarded, "the schema listed nothing to guard"
    for method, path in guarded:
        response = signed_out_client.request(method, path.replace("{id}", "1"))
        assert response.status_code == 401, f"{method.upper()} {path} answered {response.status_code}"


def test_a_cookie_nobody_signed_is_refused(signed_out_client: TestClient) -> None:
    """The cookie is signed rather than merely present, so writing one by hand fails."""
    signed_out_client.cookies.set(COOKIE_NAME, "signed-in")

    assert signed_out_client.get("/api/session").status_code == 401


def test_a_cookie_signed_with_another_secret_is_refused(
    signed_out_client: TestClient, settings: Settings
) -> None:
    stranger = TestClient(create_app(settings.model_copy(update={"session_secret": "elsewhere"})))
    stranger.post("/api/session", json={"pin": settings.pin})
    forged = stranger.cookies.get(COOKIE_NAME)
    assert forged is not None

    signed_out_client.cookies.set(COOKIE_NAME, forged)

    assert signed_out_client.get("/api/session").status_code == 401


def test_a_signed_in_device_is_never_asked_again(
    client: TestClient, settings: Settings
) -> None:
    """The cookie carries its own proof, so a Pi that rebooted between the two Parents'
    evenings does not send either of them back to the PIN screen."""
    assert client.get("/api/session").status_code == 200

    after_a_restart = TestClient(create_app(settings))
    after_a_restart.cookies.set(COOKIE_NAME, client.cookies[COOKIE_NAME])

    assert after_a_restart.get("/api/session").status_code == 200


def test_the_pin_is_configuration_rather_than_a_row(settings: Settings) -> None:
    """Changing it is an edit to `.env` and a restart; nothing in the Diary knows it."""
    rekeyed = TestClient(create_app(settings.model_copy(update={"pin": "9182"})))

    assert rekeyed.post("/api/session", json={"pin": settings.pin}).status_code == 401
    assert rekeyed.post("/api/session", json={"pin": "9182"}).status_code == 204


def test_the_stack_refuses_to_start_without_a_pin() -> None:
    """A PIN with a default would be a PIN committed to the repository."""
    for missing in ({"pin": ""}, {"session_secret": ""}):
        try:
            Settings(database_url="postgresql+psycopg://x@localhost/x", **missing)  # type: ignore[arg-type]
        except ValueError as refusal:
            assert ".env" in str(refusal)
        else:
            raise AssertionError(f"started with {missing}")
