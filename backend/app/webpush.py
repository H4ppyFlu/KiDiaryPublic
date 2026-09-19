"""Sending one notification to one Device, by the Web Push protocol.

There is no account and no connection to a phone here. A push service — Apple's,
Google's, Mozilla's; whichever one the browser chose — holds the subscription, and it
accepts a notification for it on two conditions: the request is signed by the VAPID key
the browser was holding when it subscribed (`vapid.py`), and the body is encrypted to
the two keys the browser handed over with the endpoint (`push.py`). The push service
is a courier that can read neither the sender's identity nor the message.

That is why this file is mostly cryptography. Three standards meet in it:

- **RFC 8291** derives the key the body is encrypted with, from an ECDH between a key
  pair generated for this one message and the Device's `p256dh`, salted with its `auth`
  secret. Neither the push service nor anybody watching it can read the Prompt.
- **RFC 8188** is the shape of the body those keys encrypt into: a header carrying the
  salt and the public half of that one-message key pair, then a single AES-GCM record.
- **RFC 8292** is the `Authorization` header: a JWT for the push service's own origin,
  signed with the private VAPID half, saying who is sending and until when.

It is written out here rather than taken from a library for the reason the rest of the
stack is: this is a project to learn the machinery on, and the machinery is three
hundred lines. `test_web_push.py` holds it to RFC 8291's own published example, which
is a stronger check than a library's version number — a mistake anywhere in the
derivation produces a different body, and the test would say so.

Nothing here knows about Parents, evenings or Prompts. `scheduler.py` decides what to
send and to whom; this only gets it there.
"""

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.vapid import Vapid

#: One AES-GCM record, big enough for anything this app sends. Written into the body's
#: header because RFC 8188 says a receiver is told the record size rather than assuming
#: one; a Prompt is two orders of magnitude short of filling it.
RECORD_SIZE = 4096

#: The most a push service will carry, header and encrypted record together. The same
#: number as the record size above, for a different reason — that one is what the
#: receiver is told, this one is what the courier accepts — and a Prompt is two orders
#: of magnitude short of either.
MOST_A_PUSH_SERVICE_TAKES = 4096

_CURVE = ec.SECP256R1()
_UNCOMPRESSED = (Encoding.X962, PublicFormat.UncompressedPoint)

#: RFC 8291 §3.4. The first combines the two key pairs and the Device's auth secret;
#: the other two split that into the key and the nonce AES-GCM wants.
_KEY_INFO = b"WebPush: info\x00"
_CEK_INFO = b"Content-Encoding: aes128gcm\x00"
_NONCE_INFO = b"Content-Encoding: nonce\x00"

#: How long a VAPID token is good for. The specification allows 24 hours; half of that
#: is enough for one evening and leaves room for a Pi whose clock has drifted.
_TOKEN_LIFETIME = timedelta(hours=12)

#: How long a push service gets to take a notification. Longer than a request to it
#: should ever need, short enough that a service which has stopped answering does not
#: hold up the other Parent's evening.
_TIMEOUT = 10.0


@dataclass(frozen=True)
class Device:
    """One subscription, as much of it as sending needs.

    The same three columns `push_subscriptions` holds, copied out so that nothing below
    this line touches the database or an ORM row that may have expired.
    """

    endpoint: str
    p256dh_key: str
    auth_key: str


@dataclass(frozen=True)
class Notification:
    """What a phone shows. Read by `sw.ts`, which is the other half of this dataclass
    and has to keep saying the same field names."""

    title: str
    body: str
    #: How long the push service should hold this if the phone is unreachable. The
    #: scheduler asks for the rest of the Diary day: a Prompt about today, arriving
    #: tomorrow, is a notification that has outlived its own question.
    expires_in: timedelta

    def as_payload(self) -> bytes:
        return json.dumps({"title": self.title, "body": self.body}).encode()


class PushFailed(Exception):
    """A notification that did not get there. Carries the push service's answer, if it
    gave one, because "410 Gone" and "the Pi has no network" are different problems."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def device_is_gone(self) -> bool:
        """The subscription no longer exists. The phone uninstalled the app, cleared
        its site data, or the push service expired it; nothing will ever be delivered
        to that endpoint again."""
        return self.status in (404, 410)


class PushSender(Protocol):
    def send(self, device: Device, notification: Notification) -> None:
        """Deliver this notification, or raise `PushFailed`."""
        ...


class WebPush:
    """The real sender: one HTTP client, one VAPID pair, one message at a time.

    Built once by the scheduler and kept, so that the connections to the two or three
    push services the family's phones use are re-used across evenings rather than
    negotiated again each night.
    """

    def __init__(self, vapid: Vapid, http: httpx.Client | None = None) -> None:
        self._vapid = vapid
        self._signing_key = vapid.signing_key()
        # An injected client is how the suite answers as a push service without one
        # being on the network; production never passes one.
        self._http = http if http is not None else httpx.Client(timeout=_TIMEOUT)

    def send(self, device: Device, notification: Notification) -> None:
        """Encrypt this notification to the Device and post it, or raise `PushFailed`.

        Everything that can go wrong here comes out as `PushFailed`, the encryption
        included. A subscription whose keys cannot be decoded is as undeliverable as one
        the push service refuses, and the caller is a loop over the several Devices a
        Parent carries: it has to be able to lose one of them without losing the rest.
        """
        try:
            body = encrypted(
                notification.as_payload(),
                ua_public=_from_base64url(device.p256dh_key),
                auth_secret=_from_base64url(device.auth_key),
            )
        except (ValueError, TypeError) as unusable:
            raise PushFailed(f"This subscription's keys are unusable: {unusable}") from None

        if len(body) > MOST_A_PUSH_SERVICE_TAKES:
            raise PushFailed(f"{len(body)} bytes is more than a push service will carry.")

        try:
            answer = self._http.post(
                device.endpoint,
                content=body,
                headers={
                    "Authorization": self.authorization(device.endpoint),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": str(int(notification.expires_in.total_seconds())),
                },
            )
        except httpx.HTTPError as unreachable:
            raise PushFailed(f"The push service could not be reached: {unreachable}") from None

        if answer.status_code >= 400:
            raise PushFailed(
                f"The push service refused it: {answer.status_code} {answer.text[:200]}",
                status=answer.status_code,
            )

    def authorization(self, endpoint: str) -> str:
        """The VAPID header for one push service (RFC 8292).

        The token is bound to the service's origin rather than to the subscription, so
        every phone at the same vendor could share one — they are cheap enough that
        each message signs its own, and nothing has to be expired or cached.
        """
        origin = urlsplit(endpoint)
        token = _signed_token(
            {
                "aud": f"{origin.scheme}://{origin.netloc}",
                "exp": int((datetime.now(UTC) + _TOKEN_LIFETIME).timestamp()),
                # Who a push service complains to about this sender. RFC 8292 asks
                # for a contact and requires nobody to check it; Apple checks it, and
                # refuses the notification with 403 BadJwtToken over an address it will
                # not accept. `vapid.py` holds the subject to that at startup, so by
                # here it is one a push service has a chance of taking.
                "sub": self._vapid.subject,
            },
            self._signing_key,
        )
        return f"vapid t={token}, k={self._vapid.public_key}"

    def close(self) -> None:
        self._http.close()


def encrypted(
    plaintext: bytes,
    *,
    ua_public: bytes,
    auth_secret: bytes,
    salt: bytes | None = None,
    as_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """One `aes128gcm` body, ready to be POSTed (RFC 8291 §3, RFC 8188 §2).

    The salt and the sending key pair are generated here and used for this one message.
    They are arguments only so that the test can hand over RFC 8291's published example
    and compare the bytes; production never passes either.
    """
    salt = salt if salt is not None else secrets.token_bytes(16)
    as_private = as_private if as_private is not None else ec.generate_private_key(_CURVE)

    receiver = ec.EllipticCurvePublicKey.from_encoded_point(_CURVE, ua_public)
    as_public = as_private.public_key().public_bytes(*_UNCOMPRESSED)

    # The shared secret is worth nothing on its own: anybody who intercepted the
    # subscription would have the same one. The auth secret, which travels only from
    # the browser to us, is what salts it into a key only this Pi can derive.
    shared = as_private.exchange(ec.ECDH(), receiver)
    keying_material = _hkdf(
        shared, salt=auth_secret, info=_KEY_INFO + ua_public + as_public, length=32
    )

    key = _hkdf(keying_material, salt=salt, info=_CEK_INFO, length=16)
    nonce = _hkdf(keying_material, salt=salt, info=_NONCE_INFO, length=12)

    # 0x02 is RFC 8188's delimiter for the last record, and this is the only record.
    # The padding it also allows is not used: a Prompt's length is not a secret worth
    # obscuring from a push service that can already see who is sending to whom.
    record = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)

    header = salt + RECORD_SIZE.to_bytes(4, "big") + len(as_public).to_bytes(1, "big") + as_public
    return header + record


def _hkdf(secret: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    """Extract-then-expand in one call, which is exactly what RFC 8291 asks for at each
    of its three steps."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(secret)


def _signed_token(claims: dict[str, object], signing_key: ec.EllipticCurvePrivateKey) -> str:
    """A JWT signed with ES256, written out because it is three lines and a dependency.

    The one trap is the signature's encoding: `cryptography` produces the DER sequence
    every other protocol wants, and JWS wants the two 32-byte halves laid end to end.
    """
    header = _to_base64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    payload = _to_base64url(json.dumps(claims).encode())
    signed = f"{header}.{payload}".encode()

    r, s = decode_dss_signature(signing_key.sign(signed, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return f"{header}.{payload}.{_to_base64url(signature)}"


def _to_base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _from_base64url(value: str) -> bytes:
    """What a browser sent, as bytes. Padding is restored because a browser strips it
    and `b64decode` insists on it."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
