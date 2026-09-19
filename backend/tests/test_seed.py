"""What the seed leaves behind: one Child, two Parents and the Prompt bank."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Child, Parent, Prompt
from app.seed import PROMPT_BANK, seed

#: Everything that could change something. The API offers none of them for Prompts.
EDITING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def test_the_prompt_bank_holds_the_seeded_prompts(session: Session) -> None:
    asked = set(session.scalars(select(Prompt.text).where(Prompt.is_active)))

    assert asked == set(PROMPT_BANK)


def test_the_bank_matches_the_document_it_is_copied_from() -> None:
    """`docs/prompt-bank.md` is the source of truth and the two are kept in step by hand
    (ADR-0004). By hand is exactly why this is worth a test."""
    # `/app/docs/prompt-bank.md` in the container, where Compose mounts it; two levels
    # up from this file in a checkout. Tried in that order, because the suite runs in
    # the container and that is the path it will actually find.
    here = Path(__file__).resolve()
    document = next(
        path
        for path in (parent / "docs" / "prompt-bank.md" for parent in here.parents[1:3])
        if path.is_file()
    )
    table = document.read_text("utf-8")
    documented = [
        row.strip().strip("|").split("|")[1].strip()
        for row in table.splitlines()
        if row.startswith("|") and not row.startswith("|---") and "| Prompt |" not in row
    ]

    assert documented == list(PROMPT_BANK)


def test_a_prompt_taken_out_of_the_bank_is_retired_rather_than_deleted(
    session: Session, settings: Settings
) -> None:
    """The bank is edited by editing the seed, so a Prompt dropped from it has to stop
    being asked — while staying on record, because Answers point at it."""
    retired = Prompt(text="Was war heute ganz und gar anders?")
    session.add(retired)
    session.flush()

    seed(session, settings)

    session.refresh(retired)
    assert retired.is_active is False
    assert session.get(Prompt, retired.id) is not None


def test_a_prompt_put_back_into_the_bank_is_asked_again(
    session: Session, settings: Settings
) -> None:
    """The row is still there under the same unique text, so it is woken rather than
    added a second time."""
    before = session.scalar(select(func.count()).select_from(Prompt))
    was_retired = session.scalar(select(Prompt).where(Prompt.text == PROMPT_BANK[0]))
    assert was_retired is not None
    was_retired.is_active = False
    session.flush()

    seed(session, settings)

    session.refresh(was_retired)
    assert was_retired.is_active is True
    assert session.scalar(select(func.count()).select_from(Prompt)) == before


def test_both_parents_are_seeded(session: Session) -> None:
    parents = session.scalars(select(Parent).order_by(Parent.position)).all()

    assert [parent.name for parent in parents] == ["Mama", "Papa"]


def test_seeding_again_duplicates_nothing(session: Session, settings: Settings) -> None:
    """The seed runs on every start, so a restart must not grow the Prompt bank."""
    seed(session, settings)

    assert session.scalar(select(func.count()).select_from(Prompt)) >= len(PROMPT_BANK)
    assert set(session.scalars(select(Prompt.text).where(Prompt.is_active))) == set(PROMPT_BANK)
    assert session.scalar(select(func.count()).select_from(Parent)) == 2
    assert session.scalar(select(func.count()).select_from(Child)) == 1


def test_prompts_cannot_be_edited_through_the_api(client: TestClient) -> None:
    """The bank is seeded, not managed in-app (ADR-0004), so the API offers no way in."""
    for method in EDITING_METHODS:
        for path in ("/api/prompts", "/api/prompts/1"):
            assert client.request(method, path).status_code in {404, 405}, f"{method} {path}"

    paths: dict[str, dict[str, object]] = client.get("/openapi.json").json()["paths"]
    editing = {
        f"{method.upper()} {path}"
        for path, operations in paths.items()
        if "prompt" in path.lower()
        for method in operations
        if method.upper() in EDITING_METHODS
    }
    assert editing == set()


def test_a_child_already_on_record_is_not_rewritten_by_configuration(
    client: TestClient, session: Session, settings: Settings
) -> None:
    """A restart with the wrong configuration — a missing `.env` — must not replace a
    birthdate that has been captured, because it cannot be reconstructed (ADR-0002)."""
    placeholders = {"child_name": "Platzhalter", "child_birthdate": date(2024, 1, 1)}
    seed(session, settings.model_copy(update=placeholders))

    body = client.get("/api/child").json()
    assert body["name"] == "Testkind"
    assert body["birthdate"] == "2022-03-15"
    assert session.scalar(select(func.count()).select_from(Child)) == 1
