"""The Web Push protocol itself: the encrypted body, and the header that signs it.

Everything else in this suite asserts what a Parent can observe. This file cannot: what
it is about happens between this Pi and a push service the tests have no access to, and
a phone is the only place it is ever visible. So it is held to the published standard
instead — RFC 8291 §5 encrypts a known sentence with known keys and prints the bytes
that must come out, and this reproduces them.

That example is a better check than a round trip through our own code would be. Getting
an info string or a derivation step wrong would still decrypt happily against a mistake
made the same way twice; it cannot produce the RFC's bytes.
"""

import base64
import json
from datetime import timedelta

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.vapid import Vapid, generate
from app.webpush import Device, Notification, PushFailed, WebPush, encrypted


def from_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def to_base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class TheRfc8291Example:
    """Section 5 and Appendix A of RFC 8291, verbatim. The salt and the sender's key
    pair are fixed there so that the encryption has exactly one right answer."""

    plaintext = b"When I grow up, I want to be a watermelon"
    auth_secret = "BTBZMqHH6r4Tts7J_aSIgg"
    ua_public = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
    as_private = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
    salt = "DGv6ra1nlYgDCS1FRnbzlw"
    body = (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
        "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
        "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_the_encrypted_body_is_the_one_the_standard_publishes() -> None:
    """A single byte wrong anywhere — an info string, the order of the two public keys,
    the padding delimiter — and this is a different string."""
    example = TheRfc8291Example
    sender = ec.derive_private_key(
        int.from_bytes(from_base64url(example.as_private), "big"), ec.SECP256R1()
    )

    body = encrypted(
        example.plaintext,
        ua_public=from_base64url(example.ua_public),
        auth_secret=from_base64url(example.auth_secret),
        salt=from_base64url(example.salt),
        as_private=sender,
    )

    assert to_base64url(body) == example.body


def test_every_notification_is_encrypted_under_its_own_key() -> None:
    """The salt and the sending key pair are generated per message. Two identical
    Prompts must not produce identical bytes on the wire: a push service watching the
    family's evenings would otherwise learn which Prompt is which without a key."""
    example = TheRfc8291Example
    twice = [
        encrypted(
            example.plaintext,
            ua_public=from_base64url(example.ua_public),
            auth_secret=from_base64url(example.auth_secret),
        )
        for _ in range(2)
    ]

    assert twice[0] != twice[1]


A_PHONE = Device(
    endpoint="https://push.example.test/subscriptions/aaa111",
    p256dh_key=TheRfc8291Example.ua_public,
    auth_key=TheRfc8291Example.auth_secret,
)

AN_EVENING_NOTIFICATION = Notification(
    title="Kidiary", body="Was war heute neu?", expires_in=timedelta(hours=8)
)


@pytest.fixture
def vapid(vapid_pair: tuple[str, str]) -> Vapid:
    public_key, private_key = vapid_pair
    return Vapid(public_key=public_key, private_key=private_key, subject="mailto:eltern@example.test")


def a_push_service(answer: httpx.Response, seen: list[httpx.Request]) -> httpx.Client:
    """A client that answers as a push service would, and keeps what it was sent."""

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_a_notification_is_posted_as_the_push_service_expects(vapid: Vapid) -> None:
    seen: list[httpx.Request] = []
    sending = WebPush(vapid, http=a_push_service(httpx.Response(201), seen))

    sending.send(A_PHONE, AN_EVENING_NOTIFICATION)

    (request,) = seen
    assert str(request.url) == A_PHONE.endpoint
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["content-type"] == "application/octet-stream"
    # Eight hours, in seconds: the push service holds it only while the Prompt it
    # carries is still about today.
    assert request.headers["ttl"] == "28800"
    # Encrypted, which is the whole point — the Prompt must not be legible to a courier.
    assert AN_EVENING_NOTIFICATION.body.encode() not in request.content


def test_the_authorization_header_proves_who_is_sending(vapid: Vapid) -> None:
    """The push service accepts a notification because this token verifies against the
    same key the phone subscribed with. Checked here the way it is checked there."""
    seen: list[httpx.Request] = []
    sending = WebPush(vapid, http=a_push_service(httpx.Response(201), seen))

    sending.send(A_PHONE, AN_EVENING_NOTIFICATION)

    (request,) = seen
    scheme, credentials = request.headers["authorization"].split(" ", 1)
    parts = dict(part.strip().split("=", 1) for part in credentials.split(","))
    assert scheme == "vapid"
    assert parts["k"] == vapid.public_key

    header, payload, signature = parts["t"].split(".")
    assert json.loads(from_base64url(header)) == {"typ": "JWT", "alg": "ES256"}
    claims = json.loads(from_base64url(payload))
    # Bound to the push service's origin and to nothing else in the URL: the path names
    # the subscription, and a token that carried it would be a capability to that phone.
    assert claims["aud"] == "https://push.example.test"
    assert claims["sub"] == "mailto:eltern@example.test"

    raw = from_base64url(signature)
    signed = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    public_key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), from_base64url(vapid.public_key)
    )
    public_key.verify(signed, f"{header}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))


def test_a_token_signed_by_another_pi_would_not_verify(vapid: Vapid) -> None:
    """The negative of the test above: replacing the key pair in `.env` really does
    stop every device that subscribed to the old one, which is what
    `docs/push-notifications.md` warns."""
    seen: list[httpx.Request] = []
    WebPush(vapid, http=a_push_service(httpx.Response(201), seen)).send(
        A_PHONE, AN_EVENING_NOTIFICATION
    )
    another_public_key, _ = generate()

    (request,) = seen
    parts = dict(
        part.strip().split("=", 1)
        for part in request.headers["authorization"].split(" ", 1)[1].split(",")
    )
    header, payload, signature = parts["t"].split(".")
    raw = from_base64url(signature)
    signed = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )

    stranger = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), from_base64url(another_public_key)
    )
    with pytest.raises(InvalidSignature):
        stranger.verify(signed, f"{header}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))


def test_a_push_service_that_refuses_says_so_loudly(vapid: Vapid) -> None:
    sending = WebPush(vapid, http=a_push_service(httpx.Response(400, text="bad"), []))

    with pytest.raises(PushFailed) as refused:
        sending.send(A_PHONE, AN_EVENING_NOTIFICATION)

    assert not refused.value.device_is_gone


def test_a_subscription_the_push_service_has_forgotten_is_recognised(vapid: Vapid) -> None:
    """410 is the one refusal that means something about the row rather than the
    request: nothing will ever reach that endpoint again."""
    sending = WebPush(vapid, http=a_push_service(httpx.Response(410), []))

    with pytest.raises(PushFailed) as gone:
        sending.send(A_PHONE, AN_EVENING_NOTIFICATION)

    assert gone.value.device_is_gone


def test_a_subscription_whose_keys_are_unusable_fails_like_any_other(vapid: Vapid) -> None:
    """A row whose `p256dh` is not a point on the curve — corrupted, or written by hand
    — must fail the way a refused push does. The caller is a loop over the Devices one
    Parent carries, and a `ValueError` out of the encryption would take the rest of
    them with it."""
    a_phone_with_a_broken_key = Device(
        endpoint=A_PHONE.endpoint, p256dh_key="not-a-key-at-all", auth_key=A_PHONE.auth_key
    )
    sending = WebPush(vapid, http=a_push_service(httpx.Response(201), []))

    with pytest.raises(PushFailed):
        sending.send(a_phone_with_a_broken_key, AN_EVENING_NOTIFICATION)


def test_a_push_service_that_cannot_be_reached_is_a_failure_not_a_crash(vapid: Vapid) -> None:
    """A Pi that has lost its network is the ordinary case, not an exceptional one, and
    `scheduler.py` catches this to get to the other Parent."""

    def refuse_to_connect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to the push service")

    sending = WebPush(vapid, http=httpx.Client(transport=httpx.MockTransport(refuse_to_connect)))

    with pytest.raises(PushFailed):
        sending.send(A_PHONE, AN_EVENING_NOTIFICATION)
