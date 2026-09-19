"""The key pair that identifies this Pi to a push service, and nothing else.

Web Push has no accounts. A push service accepts a notification for a subscription
because the request is signed by the same key the browser was holding when it
subscribed — that pair is VAPID, and it is one P-256 key: the public half is the
65-byte uncompressed point a browser wants as `applicationServerKey`, the private half
the 32-byte scalar, both base64url without padding. That encoding is what every Web
Push library and every browser speaks, so it is also what `.env` holds.

Neither half is in this repository or in the image (ADR-0007 builds the image on the
Pi; the keys arrive beside it in `.env`, which is not committed). A stack without them
starts and runs and simply cannot offer notifications — `GET /api/push/key` says so and
the app shows it. A stack with a *malformed* pair refuses to start instead, because
that is a mis-paste, and the alternative is finding out about it on a phone that has
already spent its one permission prompt. The same goes for `VAPID_SUBJECT`, which is a
contact rather than a key and is checked for the same reason: Apple refuses a
notification signed with an address it will not accept.

Generate a pair with:

    docker compose run --rm --no-deps api python -m app.vapid
"""

import base64
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.config import Settings

#: The uncompressed point: one marker byte and the two 32-byte coordinates.
_PUBLIC_KEY_BYTES = 65

#: The private scalar, big-endian.
_PRIVATE_KEY_BYTES = 32

#: P-256. Web Push allows no other curve.
_CURVE = ec.SECP256R1()

_UNCOMPRESSED = (Encoding.X962, PublicFormat.UncompressedPoint)


@dataclass(frozen=True)
class Vapid:
    """A configured pair that has been checked, so that everything downstream of it
    may assume it is one.

    `public_key` is what a browser subscribes with; the private half and the subject
    are what `webpush.py` signs each notification with, so that the push service
    accepts it as coming from the sender the phone subscribed to.
    """

    public_key: str
    private_key: str
    #: Who a push service should complain to about this sender. RFC 8292 asks for a
    #: contact and requires nobody to check it; Apple checks it, and refuses the whole
    #: notification over one it will not accept. Checked by `_checked_subject` before
    #: this dataclass exists, so everything downstream may assume it is deliverable.
    subject: str

    def signing_key(self) -> ec.EllipticCurvePrivateKey:
        """The private half as a key that can sign, for the VAPID header on every push
        (`webpush.py`). Rebuilt from the scalar rather than kept alongside it: the pair
        has already been checked by the time this dataclass exists, so this cannot fail
        for a `Vapid` that was handed out."""
        scalar = _decode("VAPID_PRIVATE_KEY", self.private_key, _PRIVATE_KEY_BYTES)
        return ec.derive_private_key(int.from_bytes(scalar, "big"), _CURVE)


#: The two schemes RFC 8292 allows the contact to use.
_CONTACT_SCHEMES = ("mailto:", "https://")


def _checked_subject(subject: str) -> str:
    """`VAPID_SUBJECT`, if a push service will accept it.

    RFC 8292 asks for a contact a push service can complain to and does not require
    anybody to check it. **Apple checks it**, and refuses the whole notification with
    `403 {"reason":"BadJwtToken"}` when it does not like the answer — at the hour the
    notification was due, against a subscription that is perfectly valid, leaving one
    line in a log nobody reads until the morning after.

    So it is checked here, at startup, beside the pair it travels with and for the same
    reason: the alternative is a deployment that looks finished and silently never wakes
    anybody. `mailto:kidiary@localhost` shipped as the default and is exactly such a
    subject, which made the first real evening on a new Pi a guaranteed failure.

    The rule is only what can be known here: a scheme a contact may use, and a host with
    a dot in it. Whether anybody reads that address is not this function's business.
    """
    value = subject.strip()

    # Matched against a lowered copy, because a URI scheme is case-insensitive (RFC 3986)
    # and push services take `MAILTO:` as readily as `mailto:`. The value itself keeps the
    # capitalisation it was given; only the comparison is folded.
    scheme = next((known for known in _CONTACT_SCHEMES if value.lower().startswith(known)), None)

    if scheme == "mailto:":
        # Everything after the last `@`, so that a local part containing one does not
        # move the domain. An address with no `@` leaves this empty, and it fails below.
        _, _, host = value[len(scheme):].rpartition("@")
    elif scheme is not None:
        host = urlsplit(value).hostname or ""
    else:
        raise ValueError(
            f"VAPID_SUBJECT must be one of {' or '.join(_CONTACT_SCHEMES)} and "
            f"{subject!r} is neither. A push service refuses a notification whose "
            'contact it will not accept, with 403 {"reason":"BadJwtToken"}.'
        )

    # A dot is the whole of it: it separates `example.com` from `localhost` and `pi`,
    # which are the two ways this is got wrong — a default nobody changed, and a
    # hostname that means something on one machine and nothing to Apple.
    if "." not in host.strip("."):
        raise ValueError(
            f"VAPID_SUBJECT is {subject!r}, whose host {host!r} is not a domain a push "
            "service can deliver to. Apple refuses the notification rather than the "
            'address, with 403 {"reason":"BadJwtToken"}, hours later and somewhere else. '
            "Use a real address you read, such as mailto:you@example.com."
        )

    return value


def configured_vapid(settings: Settings) -> Vapid | None:
    """The pair from the environment, nothing if there is none, or a startup failure.

    Called while the app is being built, so a bad paste stops the container rather
    than one phone.
    """
    public = settings.vapid_public_key.strip()
    private = settings.vapid_private_key.strip()

    if not public and not private:
        return None
    if not public or not private:
        raise ValueError(
            "VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are two halves of one key: "
            "set both, or neither to run without notifications."
        )

    point = _decode("VAPID_PUBLIC_KEY", public, _PUBLIC_KEY_BYTES)
    scalar = _decode("VAPID_PRIVATE_KEY", private, _PRIVATE_KEY_BYTES)

    try:
        offered = ec.EllipticCurvePublicKey.from_encoded_point(_CURVE, point)
        derived = ec.derive_private_key(int.from_bytes(scalar, "big"), _CURVE).public_key()
    except ValueError as unusable:
        raise ValueError(f"The VAPID keys are not a P-256 key pair: {unusable}") from unusable

    # Two valid keys that are not each other's half is the likely mis-paste — a new
    # pair generated over half an old one — and it is silent everywhere else: the
    # browser subscribes happily and the push is refused months later.
    if offered.public_bytes(*_UNCOMPRESSED) != derived.public_bytes(*_UNCOMPRESSED):
        raise ValueError(
            "VAPID_PUBLIC_KEY is not the public half of VAPID_PRIVATE_KEY. "
            "Generate a fresh pair with `python -m app.vapid` and replace both."
        )

    return Vapid(
        public_key=public, private_key=private, subject=_checked_subject(settings.vapid_subject)
    )


def generate() -> tuple[str, str]:
    """A fresh pair, public first, in the encoding `.env` holds."""
    private_key = ec.generate_private_key(_CURVE)
    point = private_key.public_key().public_bytes(*_UNCOMPRESSED)
    scalar = private_key.private_numbers().private_value.to_bytes(_PRIVATE_KEY_BYTES, "big")
    return _encode(point), _encode(scalar)


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode(name: str, value: str, expected: int) -> bytes:
    # `validate=True`, so that characters outside the alphabet are an error rather
    # than something to skip over: a key with a stray quote around it is a mis-paste.
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError as unreadable:
        raise ValueError(f"{name} is not base64url: {unreadable}") from unreadable
    if len(raw) != expected:
        raise ValueError(
            f"{name} decodes to {len(raw)} bytes rather than {expected}. "
            "It is probably truncated, or the two keys are the wrong way round."
        )
    return raw


if __name__ == "__main__":
    public_key, private_key = generate()
    # Paste-ready, comment included: `.env` keeps the line and the next reader learns
    # where it came from.
    print("# A VAPID key pair. Keep the private half to yourself; changing either")
    print("# half silently stops every device that has already subscribed.")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    print(f"VAPID_PRIVATE_KEY={private_key}")
