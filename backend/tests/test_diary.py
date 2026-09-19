"""Reading the Diary back.

The other half of the app: the Sitting is where Answers are written, this is what they
were written for. One Diary, jointly readable, holding both Parents' Answers interleaved
(ADR-0001) — so the tests below are mostly about what a Parent sees of the *other* one's
evening, and about the Child's age, which is the label that makes an archive read as a
record of a person growing up rather than a list of dates (ADR-0002).

Days come back newest first, because the evening just gone is the one being read.
"""

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from an_evening import (
    AN_EVENING,
    BERLIN,
    THAT_DIARY_DAY,
    THE_DAY_BEFORE,
    answer,
)

pytestmark = pytest.mark.usefixtures("empty_diary")

# The Child the test settings seed was born on 15 March 2022, so on `AN_EVENING` —
# 12 May 2026 — they are four years and one month old.
AGE_THAT_EVENING = {"years": 4, "months": 1, "label": "4 Jahre, 1 Monat"}


def diary(client: TestClient) -> list[dict]:
    """The whole Diary as a Parent reads it: Diary days, newest first."""
    response = client.get("/api/diary")
    assert response.status_code == 200, response.text
    return response.json()["days"]


def test_an_empty_diary_is_an_empty_diary_rather_than_an_error(client: TestClient) -> None:
    """Read on the first evening, before either Parent has written anything. The phone
    has to have something to render, and "no days" is it."""
    assert diary(client) == []


def test_both_parents_answers_arrive_in_one_list(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The Diary is one archive, not two accounts side by side (ADR-0001): each Parent
    reads it to see the part of the day they were not there for."""
    set_now(AN_EVENING)
    answer(mama, "Sie hat heute zum ersten Mal alleine gegessen.")
    answer(papa, "Beim Zähneputzen gelacht wie verrückt.")

    written = [entry["text"] for day in diary(mama) for entry in day["answers"]]

    assert sorted(written) == [
        "Beim Zähneputzen gelacht wie verrückt.",
        "Sie hat heute zum ersten Mal alleine gegessen.",
    ]


def test_the_diary_reads_newest_first(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The evening just gone is the first thing on the screen."""
    set_now(THE_DAY_BEFORE)
    answer(mama, "Gestern.")
    set_now(AN_EVENING)
    answer(mama, "Heute.")

    days = diary(mama)

    assert [day["diary_day"] for day in days] == ["2026-05-12", "2026-05-11"]
    assert days[0]["answers"][0]["text"] == "Heute."


def test_each_answer_carries_its_prompt_and_its_author(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """A bare sentence stops making sense within a year; the question it answered is
    what keeps it readable, and the name is whose voice it is."""
    set_now(AN_EVENING)
    hers = answer(mama, "Ihre Antwort.")["answered"]
    his = answer(papa, "Seine Antwort.")["answered"]

    by_text = {
        entry["text"]: entry for day in diary(mama) for entry in day["answers"]
    }

    assert by_text["Ihre Antwort."]["prompt"] == hers["text"]
    assert by_text["Ihre Antwort."]["author"]["name"] == "Mama"
    assert by_text["Seine Antwort."]["prompt"] == his["text"]
    assert by_text["Seine Antwort."]["author"]["name"] == "Papa"


def test_a_diary_day_is_labelled_with_the_childs_age_on_it(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The highest-value derived field in an archive meant to be read years later
    (ADR-0002), and it belongs to the day rather than to each sentence written on it."""
    set_now(AN_EVENING)
    answer(mama)

    assert diary(mama)[0]["age"] == AGE_THAT_EVENING


def test_an_age_is_the_age_then_rather_than_the_age_now(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Read four years on, an old evening still says how old the Child was that day."""
    set_now(datetime(2023, 4, 20, 20, 0, tzinfo=BERLIN))
    answer(mama, "Damals.")

    set_now(AN_EVENING)
    answer(mama, "Heute.")

    days = diary(mama)

    assert days[0]["age"] == AGE_THAT_EVENING
    assert days[-1]["age"] == {"years": 1, "months": 1, "label": "1 Jahr, 1 Monat"}


def test_within_one_diary_day_the_newest_answer_comes_first(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)
    answer(mama, "Als Erstes geschrieben.")
    answer(mama, "Als Zweites geschrieben.")

    assert [entry["text"] for entry in diary(mama)[0]["answers"]] == [
        "Als Zweites geschrieben.",
        "Als Erstes geschrieben.",
    ]


def test_both_parents_read_the_same_diary(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """There is one Diary, not one per Parent, and neither of them has a private
    corner of it (ADR-0001)."""
    set_now(AN_EVENING)
    answer(mama, "Ihre Antwort.")
    answer(papa, "Seine Antwort.")

    assert diary(mama) == diary(papa)


def test_an_answer_written_at_half_past_one_is_read_back_on_the_evening_it_belongs_to(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """A Diary day runs 04:00 to 04:00 (ADR-0004), and the Diary is where that stops
    being an implementation detail: a late night is one evening, not two."""
    set_now(AN_EVENING)
    answer(mama, "Vor dem Schlafengehen.")

    set_now(datetime(2026, 5, 13, 1, 30, tzinfo=BERLIN))
    answer(mama, "Nachts noch eingefallen.")

    days = diary(mama)

    assert len(days) == 1
    assert days[0]["diary_day"] == THAT_DIARY_DAY.isoformat()
    assert len(days[0]["answers"]) == 2
