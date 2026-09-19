"""The shared PIN, and the year-long cookie it buys.

Only devices already on the family tailnet can reach the app at all (ADR-0005), so this
is the second lock rather than the first: it exists so that a phone someone picks up
does not open onto the Diary. That makes one shared PIN enough — no per-Parent
passwords, no invite links, nothing to administer — and it makes the cookie long-lived,
because a login on the way to a five-second Answer would cost more than it protects.

The PIN is shared, so exchanging it says only that this device has it. Which of the two
Parents the device belongs to is a second, already-signed-in step, and the cookie is
re-issued carrying the answer (ADR-0010) — a claim rather than a credential. That gives
the cookie two valid shapes, and `GET /api/session` is where a browser learns which one
it is holding.
"""

import hmac
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, TimestampSigner
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.models import Parent
from app.parents import ParentProfile, the_parent

COOKIE_NAME = "kidiary_session"

#: A year, so that neither Parent is asked twice on the same phone (user story 32).
COOKIE_MAX_AGE = int(timedelta(days=365).total_seconds())

#: What gets signed, alone or followed by `:<parent id>`. The bare mark is here so that
#: a cookie is only ever accepted because of its signature.
_MARK = "signed-in"

#: Namespaces the signature, so a secret reused elsewhere cannot mint one of these.
_SALT = "kidiary-session"


@dataclass(frozen=True)
class Device:
    """What a valid cookie says: this device has the PIN, and — once it has said so —
    which Parent is holding it."""

    parent_id: int | None


class Sessions:
    """Issues the sign-in cookie and reads it coming back.

    The cookie carries its own proof, so nothing is kept server-side: a restarted API
    still knows both phones, and signing everyone out is a matter of changing
    `SESSION_SECRET`.
    """

    def __init__(self, secret: str, *, secure: bool) -> None:
        self._signer = TimestampSigner(secret, salt=_SALT)
        self._secure = secure

    def issue(self, response: Response, parent_id: int | None = None) -> None:
        """Set the cookie. Called twice per device: once for the PIN, once for the
        Parent — the second replacing the first rather than adding to it."""
        payload = _MARK if parent_id is None else f"{_MARK}:{parent_id}"
        response.set_cookie(
            COOKIE_NAME,
            self._signer.sign(payload).decode(),
            max_age=COOKIE_MAX_AGE,
            # The frontend never reads this; the browser only has to send it back.
            httponly=True,
            samesite="lax",
            secure=self._secure,
        )

    def read(self, cookie: str | None) -> Device | None:
        """The device the cookie describes, or nothing if it describes none."""
        if cookie is None:
            return None
        try:
            # The signer's own timestamp, not the browser's: a cookie kept past its
            # year is refused even if the browser was willing to keep sending it.
            payload = self._signer.unsign(cookie, max_age=COOKIE_MAX_AGE).decode()
        except BadSignature:
            return None

        mark, _, parent_id = payload.partition(":")
        if mark != _MARK:
            return None
        if parent_id == "":
            return Device(parent_id=None)
        # Only this application ever signs one of these, so anything else is a bug
        # here rather than a forgery; refusing it is still cheaper than trusting it.
        return Device(parent_id=int(parent_id)) if parent_id.isdigit() else None


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_sessions(request: Request) -> Sessions:
    sessions: Sessions = request.app.state.sessions
    return sessions


def require_signed_in(
    request: Request, sessions: Annotated[Sessions, Depends(get_sessions)]
) -> Device:
    """The guard every endpoint but the PIN exchange is mounted behind.

    Endpoints that need to know which Parent is writing ask for `require_parent`
    instead; this one only asks whether the device has the PIN.
    """
    device = sessions.read(request.cookies.get(COOKIE_NAME))
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in with the shared PIN."
        )
    return device


router = APIRouter()


class PinSubmission(BaseModel):
    pin: str


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_in(
    submission: PinSubmission,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[Sessions, Depends(get_sessions)],
) -> Response:
    """Exchange the shared PIN for the cookie. The one endpoint open to a device
    that has not been signed in yet."""
    if not hmac.compare_digest(submission.pin, settings.pin):
        # No cookie, and nothing said about which part was wrong.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That is not the PIN.")

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    sessions.issue(response)
    return response


class ParentChoice(BaseModel):
    parent_id: int


@router.put(
    "/session/parent",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_signed_in)],
)
def choose_parent(
    choice: ParentChoice,
    session: Annotated[Session, Depends(get_session)],
    sessions: Annotated[Sessions, Depends(get_sessions)],
) -> Response:
    """Say which of the two Parents this device belongs to.

    A replacement rather than an addition: the same cookie comes back carrying the
    Parent, and a device that picks again simply overwrites the claim (ADR-0010).
    """
    if the_parent(session, choice.parent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such Parent.")

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    sessions.issue(response, parent_id=choice.parent_id)
    return response


class SignedInAs(BaseModel):
    """Who the API takes this device to be. `parent` is null while the device has the
    PIN but has not said which Parent is holding it."""

    parent: ParentProfile | None


@router.get("/session")
def read_session(
    device: Annotated[Device, Depends(require_signed_in)],
    session: Annotated[Session, Depends(get_session)],
) -> SignedInAs:
    """What this device is still signed in as.

    The frontend asks this before it renders anything, and every answer it can give is
    a screen: a 401 puts up the PIN, a null Parent puts up "who are you?", and a Parent
    opens the Sitting.
    """
    parent = the_parent(session, device.parent_id)
    return SignedInAs(parent=ParentProfile.model_validate(parent) if parent else None)


def require_parent(
    device: Annotated[Device, Depends(require_signed_in)],
    session: Annotated[Session, Depends(get_session)],
) -> Parent:
    """The Parent writing this request, for the endpoints that store something in one's
    name. A signed-in device that has not said who it is gets 403 rather than 401: it
    needs the question, not the PIN screen again."""
    parent = the_parent(session, device.parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Say which Parent this device is."
        )
    return parent
