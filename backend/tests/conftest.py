from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import date, datetime, time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from an_evening import APushThatIsWatched, FixedClock, Pass
from app.bootstrap import migrate_and_seed
from app.chance import Dice, get_chance
from app.child import the_child
from app.clock import get_clock
from app.config import Settings
from app.db import create_session_factory
from app.models import Answer, Delivery, Parent, PushSubscription, Skip
from app.main import create_app
from app.scheduler import send_what_is_due
from app.vapid import generate


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """A `_test` database alongside the configured one, created if it is not there yet.

    Tests run against a real Postgres (never SQLite), because the queries this
    project cares about are exactly the ones that differ between engines.
    """
    configured = make_url(Settings().database_url)
    test_url = configured.set(database=f"{configured.database}_test")

    maintenance = create_engine(configured.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with maintenance.connect() as connection:
        already_there = connection.execute(
            text("select 1 from pg_database where datname = :name"),
            {"name": test_url.database},
        ).scalar_one_or_none()
        if already_there is None:
            connection.execute(text(f'create database "{test_url.database}"'))
    maintenance.dispose()

    return test_url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def vapid_pair() -> tuple[str, str]:
    """One VAPID key pair for the whole run, public half first."""
    return generate()


@pytest.fixture(scope="session")
def settings(test_database_url: str, vapid_pair: tuple[str, str]) -> Settings:
    """The configuration the whole run uses. The Child is pinned here so that the
    ages the API reports have something to be true about."""
    vapid_public_key, vapid_private_key = vapid_pair
    return Settings(
        database_url=test_database_url,
        child_name="Testkind",
        child_birthdate=date(2022, 3, 15),
        parent_one_name="Mama",
        parent_two_name="Papa",
        pin="4711",
        session_secret="a-secret-that-only-the-suite-signs-with",
        # A real pair, generated for this run rather than committed: the keys a Pi
        # holds are the one thing about a deployment that never belongs in a repo,
        # and generating them here means the suite also exercises the generator.
        vapid_public_key=vapid_public_key,
        vapid_private_key=vapid_private_key,
        # A contact on a domain that exists as a concept, because a push service checks
        # this one. `.test` is reserved by RFC 2606 precisely so that it can be written
        # down without belonging to anybody, which is what a suite wants and what the
        # default `mailto:kidiary@localhost` was not (see `vapid.py`).
        vapid_subject="mailto:eltern@example.test",
    )


@pytest.fixture(scope="session")
def fresh_database(settings: Settings) -> None:
    """Drops the schema, then rebuilds it with the real migrations and the real seed.

    Dropping first means a run never inherits rows from the run before, and going
    through `migrate_and_seed` means the tests exercise the path the Pi boots through.
    """
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("drop schema public cascade"))
        connection.execute(text("create schema public"))
    engine.dispose()

    migrate_and_seed(settings)


@pytest.fixture(scope="session")
def api(settings: Settings, fresh_database: None) -> FastAPI:
    """Built once, so the whole run shares one connection pool rather than one per test."""
    return create_app(settings)


@pytest.fixture
def signed_out_client(api: FastAPI) -> Iterator[TestClient]:
    """A device that has not been given the PIN. Only the PIN exchange answers it."""
    with TestClient(api) as test_client:
        yield test_client


@pytest.fixture
def client(signed_out_client: TestClient, settings: Settings) -> TestClient:
    """The API, driven over HTTP by a device that has been signed in.

    This is the default a test gets, because it is the state a Parent is in for all but
    the first few seconds they ever spend in the app. The PIN is exchanged through the
    real endpoint rather than by planting a cookie, so a test never signs in by a route
    a phone could not take.
    """
    response = signed_out_client.post("/api/session", json={"pin": settings.pin})
    assert response.status_code == 204, response.text
    return signed_out_client


@pytest.fixture
def sign_in_as(api: FastAPI, settings: Settings) -> Iterator[Callable[[int], TestClient]]:
    """A phone that has been given the PIN and has said which Parent is holding it.

    Each call is a separate device with its own cookie jar, so a test can put both
    Parents in the app at once and watch their evenings stay independent. Every step
    goes through the real endpoints — the PIN, the Parent list, the choice — so a test
    never arrives in a state a phone could not.
    """
    with ExitStack() as devices:

        def sign_in(position: int) -> TestClient:
            device = devices.enter_context(TestClient(api))
            assert device.post("/api/session", json={"pin": settings.pin}).status_code == 204

            parents = device.get("/api/parents").json()
            parent = next(candidate for candidate in parents if candidate["position"] == position)
            chosen = device.put("/api/session/parent", json={"parent_id": parent["id"]})
            assert chosen.status_code == 204, chosen.text
            return device

        yield sign_in


@pytest.fixture
def mama(sign_in_as: Callable[[int], TestClient]) -> TestClient:
    """The first Parent, on her own phone."""
    return sign_in_as(1)


@pytest.fixture
def papa(sign_in_as: Callable[[int], TestClient]) -> TestClient:
    """The second Parent, on his own phone."""
    return sign_in_as(2)


@pytest.fixture
def forget_this_evening(settings: Settings, fresh_database: None) -> Callable[[], None]:
    """Delete every Answer and every Skip, leaving the Child, the Parents and the bank.

    Used to clean up after a test, and used inside one to put a Parent back at the
    start of the same evening so it can be drawn twice and compared.
    """

    def forget() -> None:
        session_factory = create_session_factory(settings.database_url)
        with session_factory() as open_session:
            open_session.query(Answer).delete()
            open_session.query(Skip).delete()
            open_session.commit()

    return forget


@pytest.fixture
def empty_diary(forget_this_evening: Callable[[], None]) -> Iterator[None]:
    """Nothing answered or skipped yet, and nothing left behind afterwards.

    The database is built once for the whole run, so a test that writes Answers has to
    clear them again or the next one inherits an evening it never had.
    """
    yield
    forget_this_evening()


#: Any number would do; it only has to be the same one on every run.
A_FIXED_SEED = 20260512


@pytest.fixture(autouse=True)
def seeded_chance(api: FastAPI) -> Iterator[Callable[[int], None]]:
    """The draw's random source, pinned for every test in the run.

    Where ADR-0004's rules leave the draw free, `Chance` picks, and a suite that lets
    that be genuinely random is a suite whose failures come and go. Seeding it means a
    run that goes red goes red again on the next run. Every test starts on the same
    seed without asking; a test that wants to replay an evening re-seeds mid-way by
    calling this with a number of its own.
    """

    def seed(seed_value: int) -> None:
        # One `Dice` per seeding rather than one per request, so the draws across a
        # test are a stream rather than the same roll over and over.
        dice = Dice(seed_value)
        api.dependency_overrides[get_chance] = lambda: dice

    seed(A_FIXED_SEED)
    yield seed
    api.dependency_overrides.pop(get_chance, None)


@pytest.fixture
def set_now(api: FastAPI) -> Iterator[Callable[[datetime], None]]:
    """Place the API on a chosen moment — the evening before a birthday, 01:30 — so
    that time-dependent behaviour is asserted rather than waited for."""

    def place(moment: datetime) -> None:
        api.dependency_overrides[get_clock] = lambda: _FixedClock(moment)

    yield place
    api.dependency_overrides.pop(get_clock, None)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
def session(settings: Settings, fresh_database: None) -> Iterator[Session]:
    """A database session, for the seed's Prompt bank and Parents.

    Everything a Parent can observe is asserted over HTTP; these two have no HTTP
    surface until the draw and the Diary arrive, and until then the rows are the only
    place to see them.
    """
    session_factory = create_session_factory(settings.database_url)
    with session_factory() as open_session:
        yield open_session


@pytest.fixture
def registered(session: Session) -> Callable[[], list[PushSubscription]]:
    """Every push subscription on record, in the order they were made.

    Expired first: the endpoints write through their own session, and a scheduler pass
    through one of its own, so a row this session has already loaded would otherwise
    still be described as it was before the write.
    """

    def read() -> list[PushSubscription]:
        session.expire_all()
        return list(session.scalars(select(PushSubscription).order_by(PushSubscription.id)).all())

    return read


@pytest.fixture
def child_born_on(session: Session) -> Iterator[Callable[[date], None]]:
    """Change the birthdate on the Child on record, and put it back afterwards, so a
    calendar edge can be asserted without a second Child."""
    child = the_child(session)
    assert child is not None
    original = child.birthdate

    def place(birthdate: date) -> None:
        child.birthdate = birthdate
        session.commit()

    yield place
    child.birthdate = original
    session.commit()


@pytest.fixture
def parent_ids(session: Session) -> dict[int, int]:
    """The two seeded Parents' ids, by position, for asserting whose row is whose."""
    return {parent.position: parent.id for parent in session.scalars(select(Parent))}


@pytest.fixture
def push() -> APushThatIsWatched:
    """A push sender that keeps what it was handed instead of putting it on the wire.

    What the real one writes is held to RFC 8291's published example in
    `test_web_push.py`; what a test about an evening cares about is how many times it
    was called, and with which Prompt.
    """
    return APushThatIsWatched()


@pytest.fixture
def evening(settings: Settings) -> Pass:
    """Run one pass of the scheduler at a chosen moment.

    Each pass opens its own `Session` from its own factory and closes it again, because
    that is what a restarted container does: a test that ran two passes through one
    session would be proving something about a process that never stopped. Nothing a
    pass did survives except what it committed.

    `Chance` is seeded from the moment, so that a pass replayed at the same moment
    draws the same Prompt and a red run goes red again next time.
    """

    def pass_at(moment: datetime, sender: APushThatIsWatched) -> None:
        session_factory = create_session_factory(settings.database_url)
        with session_factory() as its_own_session:
            send_what_is_due(
                its_own_session, FixedClock(moment), Dice(int(moment.timestamp())), sender
            )

    return pass_at


@pytest.fixture
def deliveries(session: Session) -> Callable[[], list[Delivery]]:
    """Every Delivery on record. Expired first, because the pass wrote through a
    session this one may already have read from."""

    def read() -> list[Delivery]:
        session.expire_all()
        return list(session.scalars(select(Delivery).order_by(Delivery.id)).all())

    return read


@pytest.fixture
def no_evening_left_behind(session: Session) -> Iterator[None]:
    """The database is built once for the whole run, so an evening that sent something
    has to be forgotten again or the next test inherits it."""
    yield
    session.query(Delivery).delete()
    session.query(PushSubscription).delete()
    session.commit()


@pytest.fixture
def notification_times_as_seeded(session: Session) -> Iterator[None]:
    """Both Parents' notification times, put back the way the seed left them.

    Needed by every test that moves one, whether through the endpoint or by hand: the
    two Parents are seeded once for the whole run, so a time changed in one test is a
    time the next one inherits.
    """
    original = {
        parent.position: (parent.notification_time, parent.notification_time_from)
        for parent in session.scalars(select(Parent))
    }

    yield

    for parent in session.scalars(select(Parent)):
        parent.notification_time, parent.notification_time_from = original[parent.position]
    session.commit()


@pytest.fixture
def notification_time(
    session: Session, notification_times_as_seeded: None
) -> Callable[[int, time], None]:
    """Move one Parent's own notification time, in the row rather than through the app.

    For the scheduler's tests, which are about a time that has been set rather than
    about the setting of it: `notification_time_from` is left alone, which is a time
    that has counted all along. What the endpoint writes instead is
    `test_the_notification_time`.
    """

    def move(position: int, to: time) -> None:
        parent = session.scalars(select(Parent).where(Parent.position == position)).one()
        parent.notification_time = to
        session.commit()

    return move
