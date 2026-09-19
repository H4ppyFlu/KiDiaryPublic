"""The VAPID pair, and the contact that travels with it.

The pair itself is checked at startup because a mis-paste is otherwise discovered on a
phone that has already spent its one iOS permission prompt. This file adds the claim
beside it, for the same reason and with a sharper example behind it.

RFC 8292 says the `sub` claim is a contact the push service can complain to, and does
not say a push service must check it. **Apple checks it.** A subject Apple will not
accept comes back as `403 {"reason":"BadJwtToken"}` — from the push service, at the hour
the notification was due, against a subscription that is perfectly valid — and the only
place it is visible is the scheduler's log the next morning. The shipped default was
`mailto:kidiary@localhost`, which is exactly such a subject, so the first real evening on
a new deployment was guaranteed to fail. That is what these tests are here to stop.
"""

import pytest

from app.config import Settings
from app.vapid import configured_vapid, generate


def settings_with(subject: str) -> Settings:
    """A Settings carrying a real pair and the subject under test, so that only the
    subject can be what a failure is about."""
    public_key, private_key = generate()
    return Settings(
        database_url="postgresql+psycopg://x@localhost/x",
        pin="0000",
        session_secret="the-suite-signs-with-its-own",
        vapid_public_key=public_key,
        vapid_private_key=private_key,
        vapid_subject=subject,
    )


class TestASubjectAPushServiceWillAccept:
    @pytest.mark.parametrize(
        "subject",
        [
            "mailto:eltern@example.test",
            "mailto:kidiary@example.com",
            "https://example.com/contact",
            # A URI scheme is case-insensitive (RFC 3986) and push services take these,
            # so refusing them would be this check inventing a rule of its own.
            "MAILTO:eltern@example.test",
            "Https://example.com/contact",
            # Surrounding whitespace is a paste, not a different address.
            "  mailto:eltern@example.test  ",
        ],
    )
    def test_is_kept_as_it_was_given(self, subject: str) -> None:
        vapid = configured_vapid(settings_with(subject))

        assert vapid is not None
        assert vapid.subject == subject.strip()


class TestASubjectAPushServiceWillRefuse:
    def test_localhost_stops_the_stack_rather_than_one_evening(self) -> None:
        """The shipped default, and the reason this check exists at all."""
        with pytest.raises(ValueError) as refused:
            configured_vapid(settings_with("mailto:kidiary@localhost"))

        # The message has to carry the diagnosis, because the symptom it prevents
        # appears hours later, somewhere else, and says only "BadJwtToken".
        assert "VAPID_SUBJECT" in str(refused.value)

    @pytest.mark.parametrize(
        "subject",
        [
            "kidiary@example.com",  # no scheme at all
            "mailto:kidiary@localhost",  # not a routable domain
            "mailto:kidiary@pi",  # a hostname, not a domain
            "mailto:",  # a scheme and nothing else
            "ftp://example.com",  # a scheme, but not one a contact may use
            "",  # nothing
        ],
    )
    def test_is_refused_at_startup(self, subject: str) -> None:
        with pytest.raises(ValueError):
            configured_vapid(settings_with(subject))


class TestTheSubjectIsOnlyCheckedWhenThereIsAPair:
    def test_a_stack_without_notifications_does_not_care(self) -> None:
        """Empty keys are a working state — the app says it cannot offer notifications
        — and a subject nothing will ever sign with is not worth refusing to start over.
        """
        settings = Settings(
            database_url="postgresql+psycopg://x@localhost/x",
            pin="0000",
            session_secret="the-suite-signs-with-its-own",
            vapid_public_key="",
            vapid_private_key="",
            vapid_subject="mailto:kidiary@localhost",
        )

        assert configured_vapid(settings) is None
