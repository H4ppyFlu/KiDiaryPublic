"""One Prompt at a time, the Answer that draws the next, and the Diary day both land on.

The Prompt bank holds twenty Prompts (`test_seed`), and on an empty evening they are
all equally eligible, so these tests never name a Prompt they expect. They assert what
a Parent can observe instead: that something is in front of them, that what they
answered does not come back today, and that the other Parent's evening is untouched by
it. Skip and the rest of the draw order are `test_skipping`.
"""

from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from an_evening import AN_EVENING, answer
from app.models import Answer, Parent
from app.seed import PROMPT_BANK

BERLIN = ZoneInfo("Europe/Berlin")

pytestmark = pytest.mark.usefixtures("empty_diary")


def test_one_prompt_is_offered_at_a_time_with_nothing_else_to_fill_in(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Never a form of several questions (ADR-0004): the response has room for one."""
    set_now(AN_EVENING)

    body = mama.get("/api/prompt").json()

    assert set(body) == {"prompt"}
    assert body["prompt"]["text"] in PROMPT_BANK


def test_submitting_an_answer_stores_it_and_shows_the_next_prompt(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)

    sitting = answer(mama, "Er hat heute zum ersten Mal selbst die Schuhe angezogen.")

    stored = session.scalars(select(Answer)).all()
    assert len(stored) == 1
    assert stored[0].text == "Er hat heute zum ersten Mal selbst die Schuhe angezogen."
    assert stored[0].prompt_id == sitting["answered"]["id"]
    assert stored[0].diary_day == date(2026, 5, 12)

    # And the Sitting carries on without being asked again.
    assert sitting["next"] is not None
    assert sitting["next"]["id"] != sitting["answered"]["id"]


def test_an_answer_is_stored_against_the_parent_who_wrote_it(
    mama: TestClient, papa: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)

    answer(mama, "Mamas Satz.")
    answer(papa, "Papas Satz.")

    written = dict(session.execute(select(Answer.text, Parent.name).join(Parent)).all())
    assert written == {"Mamas Satz.": "Mama", "Papas Satz.": "Papa"}


def test_a_prompt_answered_today_is_never_drawn_again_today(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Answering all but one leaves the draw with a single eligible Prompt, so this
    asserts the exclusion outright rather than hoping a random draw exposes it."""
    set_now(AN_EVENING)

    answered = {answer(mama)["answered"]["id"] for _ in range(len(PROMPT_BANK) - 1)}

    for _ in range(5):
        drawn = mama.get("/api/prompt").json()["prompt"]
        assert drawn is not None
        assert drawn["id"] not in answered


def test_a_whole_evening_of_answering_empties_the_bank_and_says_so(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Twenty Answers, no Prompt twice, and then a draw with nothing in it rather than
    an error or the same Prompt forever."""
    set_now(AN_EVENING)

    answered = []
    for _ in range(len(PROMPT_BANK)):
        answered.append(answer(mama)["answered"]["id"])

    assert len(set(answered)) == len(PROMPT_BANK)
    assert mama.get("/api/prompt").json()["prompt"] is None


def test_one_parents_answers_do_not_affect_what_the_other_is_drawn(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The two evenings are drawn independently (ADR-0004), so Mama answering the bank
    empty leaves Papa a full one."""
    set_now(AN_EVENING)

    for _ in range(len(PROMPT_BANK)):
        answer(mama)
    assert mama.get("/api/prompt").json()["prompt"] is None

    assert papa.get("/api/prompt").json()["prompt"] is not None


def test_an_answer_at_half_past_one_belongs_to_the_evening_that_just_ended(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """The Diary day runs 04:00 to 04:00 (ADR-0004). A Parent still awake at 01:30 is
    writing about yesterday, and the app must not disagree with them."""
    set_now(datetime(2026, 5, 13, 1, 30, tzinfo=BERLIN))

    answer(mama)

    stored = session.scalars(select(Answer)).one()
    assert stored.diary_day == date(2026, 5, 12)

    # Still the same Diary day at 03:59: the rest of the bank is answered off before
    # four o'clock, and nothing has come back by the time the hour arrives.
    for _ in range(len(PROMPT_BANK) - 1):
        answer(mama)
    set_now(datetime(2026, 5, 13, 3, 59, tzinfo=BERLIN))

    assert mama.get("/api/prompt").json()["prompt"] is None


def test_an_answer_at_five_belongs_to_the_diary_day_that_has_begun(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    set_now(datetime(2026, 5, 13, 5, 0, tzinfo=BERLIN))

    answer(mama)

    assert session.scalars(select(Answer)).one().diary_day == date(2026, 5, 13)


def test_the_bank_refills_when_the_diary_day_turns_at_four(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """A Prompt is excluded for a Diary day, not forever: repetition over time is the
    point of a bank of twenty (ADR-0004)."""
    set_now(datetime(2026, 5, 13, 1, 30, tzinfo=BERLIN))
    for _ in range(len(PROMPT_BANK)):
        answer(mama)
    assert mama.get("/api/prompt").json()["prompt"] is None

    set_now(datetime(2026, 5, 13, 4, 0, tzinfo=BERLIN))

    assert mama.get("/api/prompt").json()["prompt"] is not None


def test_an_empty_answer_is_refused(mama: TestClient, set_now: Callable[[datetime], None]) -> None:
    """Submitting nothing is not the same as skipping, which records what it did."""
    set_now(AN_EVENING)
    drawn = mama.get("/api/prompt").json()["prompt"]

    for nothing in ("", "   ", "\n\t "):
        response = mama.post("/api/answers", json={"prompt_id": drawn["id"], "text": nothing})
        assert response.status_code == 422, response.text

    assert mama.get("/api/prompt").json()["prompt"] is not None


def test_an_answer_is_stored_without_the_whitespace_around_it(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)

    answer(mama, "  Er hat gelacht.\n")

    assert session.scalars(select(Answer)).one().text == "Er hat gelacht."


def test_a_prompt_that_is_not_in_the_bank_cannot_be_answered(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)

    response = mama.post("/api/answers", json={"prompt_id": 9999, "text": "Ins Leere."})

    assert response.status_code == 404


def test_the_same_prompt_cannot_be_answered_twice_on_one_diary_day(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """The draw already excludes it; a phone left open on yesterday's screen does not."""
    set_now(AN_EVENING)
    answered = answer(mama)["answered"]["id"]

    response = mama.post("/api/answers", json={"prompt_id": answered, "text": "Noch einmal."})

    assert response.status_code == 409
    assert len(session.scalars(select(Answer)).all()) == 1
