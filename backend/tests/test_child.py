"""The Child the Diary is about, and the age every Answer will be labelled with."""

from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

BERLIN = ZoneInfo("Europe/Berlin")

# The Child the test settings seed: born 15 March 2022.


def test_the_child_is_reported_with_a_name_and_an_age(
    client: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(datetime(2024, 7, 20, 19, 0, tzinfo=BERLIN))

    response = client.get("/api/child")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Testkind"
    assert body["birthdate"] == "2022-03-15"
    assert body["age"] == {"years": 2, "months": 4, "label": "2 Jahre, 4 Monate"}


def test_a_month_turns_on_the_day_of_the_month_the_child_was_born(
    client: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(datetime(2024, 7, 14, 22, 30, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "2 Jahre, 3 Monate"

    set_now(datetime(2024, 7, 15, 7, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "2 Jahre, 4 Monate"


def test_a_year_turns_on_the_birthday(
    client: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(datetime(2025, 3, 14, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"] == {
        "years": 2,
        "months": 11,
        "label": "2 Jahre, 11 Monate",
    }

    set_now(datetime(2025, 3, 15, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"] == {
        "years": 3,
        "months": 0,
        "label": "3 Jahre",
    }


def test_an_age_reads_as_german_rather_than_as_two_numbers(
    client: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Singulars matter: this string is shown on every Answer in the Diary."""
    set_now(datetime(2023, 4, 20, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "1 Jahr, 1 Monat"

    set_now(datetime(2022, 3, 20, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "0 Monate"


def test_a_child_born_on_a_31st_turns_a_month_on_the_1st_in_a_shorter_one(
    client: TestClient,
    set_now: Callable[[datetime], None],
    child_born_on: Callable[[date], None],
) -> None:
    """One child in fifteen has no birthday in February, and their age still has to
    read sensibly there."""
    child_born_on(date(2024, 1, 31))

    set_now(datetime(2024, 2, 29, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "0 Monate"

    set_now(datetime(2024, 3, 1, 20, 0, tzinfo=BERLIN))
    assert client.get("/api/child").json()["age"]["label"] == "1 Monat"
