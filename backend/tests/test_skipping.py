"""Skip, and the draw order it completes.

Answering is `test_sitting`; this file is the other half of ADR-0004's rule. Skipping a
Prompt keeps the Sitting going and puts it at the back of the evening's queue rather
than throwing it away: unseen Prompts come first, today's Skips return only once
nothing unseen is left, and ties go to whichever this Parent answered longest ago.

The rules are numbered here as `README.md` numbers them: 1 excludes what has been
answered today, 2 prefers the unseen to tonight's Skips, 3 prefers the least recently
answered, and 4 is `Chance` for whatever is left over. The draw is free only where rule
4 reaches, so every test below corners the earlier rules until one Prompt is eligible
and asserts that one, rather than sampling a draw and hoping.
"""

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from an_evening import (
    A_FORTNIGHT_AGO,
    AN_EVENING,
    LAST_WEEK,
    THAT_DIARY_DAY,
    answer,
    answer_the_prompt,
    drawn_for,
    skip,
    the_whole_bank,
    with_one_prompt_answered_longest_ago,
)
from app.models import Skip
from app.seed import PROMPT_BANK

pytestmark = pytest.mark.usefixtures("empty_diary")


def test_skipping_records_the_skip_and_draws_the_next_prompt(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """A Skip is recorded rather than discarded (ADR-0004), and the Sitting carries on
    in the same round trip that passed the Prompt over."""
    set_now(AN_EVENING)
    skipped = drawn_for(mama)

    instead = skip(mama, skipped["id"])

    stored = session.scalars(select(Skip)).one()
    assert stored.prompt_id == skipped["id"]
    assert stored.diary_day == THAT_DIARY_DAY

    # And the Sitting carries on: skipping is not a punishment for having opened the app.
    assert instead is not None
    assert instead["text"] in PROMPT_BANK


def test_a_prompt_skipped_today_waits_behind_every_prompt_not_yet_seen(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Rule 2. One Prompt is skipped and the other nineteen are answered off one at a
    time; the skipped one must not appear in any of them."""
    set_now(AN_EVENING)
    skipped = drawn_for(mama)

    skip(mama, skipped["id"])

    for _ in range(len(PROMPT_BANK) - 1):
        assert answer(mama)["answered"]["id"] != skipped["id"]


def test_a_prompt_skipped_today_is_offered_again_once_nothing_unseen_is_left(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Rule 2's other half. A Skip is a "not this one, yet" — with the other nineteen
    answered, the only thing left to ask is the Prompt that was passed over."""
    set_now(AN_EVENING)
    skipped = drawn_for(mama)
    skip(mama, skipped["id"])

    for _ in range(len(PROMPT_BANK) - 1):
        answer(mama)

    assert drawn_for(mama) == skipped


def test_skipping_the_whole_bank_leaves_the_whole_bank_still_to_ask(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """Skipping is not answering. A Parent who passes over all twenty has emptied
    nothing: the evening is still there to come back to, and every Skip is on record."""
    set_now(AN_EVENING)

    skipped = []
    for _ in range(len(PROMPT_BANK)):
        prompt = drawn_for(mama)
        skipped.append(prompt["id"])
        skip(mama, prompt["id"])

    assert len(set(skipped)) == len(PROMPT_BANK)
    assert len(session.scalars(select(Skip)).all()) == len(PROMPT_BANK)
    assert drawn_for(mama) is not None


def test_a_prompt_this_parent_has_never_answered_comes_before_one_they_have(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Rule 3, at its edge. "Least recently answered" puts a Prompt this Parent has
    never answered at all ahead of every Prompt they have — it is the longest ago there
    is — so a bank with one untouched Prompt in it has no freedom left to draw with."""
    set_now(A_FORTNIGHT_AGO)
    never_answered, *the_rest = the_whole_bank(mama)

    set_now(LAST_WEEK)
    for prompt_id in the_rest:
        answer_the_prompt(mama, prompt_id)

    set_now(AN_EVENING)

    assert drawn_for(mama)["id"] == never_answered


def test_the_prompt_this_parent_answered_longest_ago_wins(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """Rule 3 proper. Every Prompt has been answered once a fortnight ago; all but one
    have been answered again since, so exactly one was answered longest ago."""
    longest_ago = with_one_prompt_answered_longest_ago(mama, set_now)

    set_now(AN_EVENING)

    assert drawn_for(mama)["id"] == longest_ago


def test_the_same_evening_drawn_twice_from_the_same_seed_comes_out_the_same(
    mama: TestClient,
    set_now: Callable[[datetime], None],
    seeded_chance: Callable[[int], None],
    forget_this_evening: Callable[[], None],
) -> None:
    """Rule 4, and the reason it is a seam. Where the earlier rules leave the draw free,
    `Chance` picks — and it is seeded, so the freedom is in the app rather than in the
    suite. Nothing has been answered, so all twenty are tied and every one of these five
    draws is chance's alone."""
    set_now(AN_EVENING)

    seeded_chance(1806)
    an_evening = [answer(mama)["answered"]["id"] for _ in range(5)]

    forget_this_evening()
    seeded_chance(1806)
    the_same_evening_again = [answer(mama)["answered"]["id"] for _ in range(5)]

    assert the_same_evening_again == an_evening


def test_a_different_seed_draws_a_different_evening(
    mama: TestClient,
    set_now: Callable[[datetime], None],
    seeded_chance: Callable[[int], None],
    forget_this_evening: Callable[[], None],
) -> None:
    """The other half of the same claim: seeded, not fixed. Five draws out of twenty
    tied Prompts agree by luck about once in two million, so a draw that ignored its
    source — always the lowest id, say — would be caught here rather than admired for
    its reproducibility."""
    set_now(AN_EVENING)

    seeded_chance(1)
    one_evening = [answer(mama)["answered"]["id"] for _ in range(5)]

    forget_this_evening()
    seeded_chance(2)
    another_evening = [answer(mama)["answered"]["id"] for _ in range(5)]

    assert another_evening != one_evening


def test_the_diary_day_is_complete_only_once_every_prompt_has_been_answered(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """A whole evening of skipping and then answering everything: forty round trips that
    end in "nothing left" rather than in a loop or an error."""
    set_now(AN_EVENING)

    for _ in range(len(PROMPT_BANK)):
        skip(mama, drawn_for(mama)["id"])
    assert drawn_for(mama) is not None

    for _ in range(len(PROMPT_BANK)):
        answer(mama)

    assert drawn_for(mama) is None


def test_skipping_the_same_prompt_twice_in_one_evening_is_not_an_error(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """Skipped Prompts come back, so being passed over again is the rule working. One
    row either way — a Skip says "this Parent passed on this Prompt on this day"."""
    set_now(AN_EVENING)
    skipped = drawn_for(mama)
    skip(mama, skipped["id"])

    for _ in range(len(PROMPT_BANK) - 1):
        answer(mama)
    assert drawn_for(mama) == skipped

    assert skip(mama, skipped["id"]) == skipped
    assert len(session.scalars(select(Skip)).all()) == 1


def test_a_prompt_answered_today_cannot_also_be_skipped_today(
    mama: TestClient, session: Session, set_now: Callable[[datetime], None]
) -> None:
    """A Skip is the record of what gets dodged, so one sitting on top of an Answer
    would be noise in exactly the thing it is kept for. The draw never offers an
    answered Prompt again today; a screen left open across four o'clock does."""
    set_now(AN_EVENING)
    answered = answer(mama)["answered"]["id"]

    response = mama.post("/api/skips", json={"prompt_id": answered})

    assert response.status_code == 409
    assert session.scalars(select(Skip)).all() == []


def test_a_prompt_that_is_not_in_the_bank_cannot_be_skipped(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    set_now(AN_EVENING)

    assert mama.post("/api/skips", json={"prompt_id": 9999}).status_code == 404


def test_one_parents_skips_do_not_affect_what_the_other_is_drawn(
    mama: TestClient, papa: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """The two evenings are drawn independently (ADR-0004). Papa's history leaves one
    Prompt uniquely least-recently-answered, so his draw has no freedom in it — and Mama
    passing over that very Prompt tonight must not take it away from him."""
    longest_ago = with_one_prompt_answered_longest_ago(papa, set_now)

    set_now(AN_EVENING)
    skip(mama, longest_ago)

    assert drawn_for(papa)["id"] == longest_ago


def test_a_skip_expires_with_the_diary_day_it_was_made_on(
    mama: TestClient, set_now: Callable[[datetime], None]
) -> None:
    """"Skipped today" is the rule; a Prompt passed over last night is simply a Prompt
    again this evening, and its place in the order is its own history again."""
    longest_ago = with_one_prompt_answered_longest_ago(mama, set_now)
    # Still on the evening before, which is the one whose Skip has to expire.
    skip(mama, longest_ago)

    set_now(AN_EVENING)

    assert drawn_for(mama)["id"] == longest_ago
