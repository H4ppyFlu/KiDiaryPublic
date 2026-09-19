from datetime import date
from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the API reads from its environment. See `.env.example`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kidiary:kidiary@localhost:5432/kidiary"

    #: The built PWA. Present in the container image, absent in local development,
    #: where Vite serves the frontend itself.
    static_dir: Path = Path("static")

    #: The family's timezone. A Diary day and a notification time both mean local time.
    timezone: str = "Europe/Berlin"

    #: Who the Diary is about, and who keeps it. These are configuration rather than
    #: literals in the seed so that a real child's name never lands in the repository;
    #: the defaults are placeholders that let the stack start with no setup at all.
    child_name: str = "Kind"
    child_birthdate: date = date(2024, 1, 1)
    parent_one_name: str = "Mama"
    parent_two_name: str = "Papa"

    #: The PIN both Parents type once per device, and the secret that signs the cookie
    #: they get for it. Unlike everything above, neither has a usable default: a PIN
    #: written into the repository is not a PIN, and a secret invented at each start
    #: would sign both phones out every time the Pi reboots.
    pin: str = ""
    session_secret: str = ""

    #: The key pair that identifies this Pi to a push service, and the contact a push
    #: service can complain to. Unset is a working state: the stack runs and says it
    #: cannot offer notifications. A malformed pair is not — see `vapid.py`.
    #:
    #: The subject has no usable default either, for the same reason the PIN has none:
    #: `mailto:kidiary@localhost` was one, and Apple refuses every notification signed
    #: with it. A stack with keys and no real contact fails at startup rather than at
    #: the hour somebody was expecting to be asked.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""

    #: Whether the sign-in cookie is marked `Secure`. False so that the stack works on
    #: `http://localhost` in development; true behind Tailscale Serve, which is the
    #: only way the app is ever reached from a phone (ADR-0005).
    cookie_secure: bool = False

    @model_validator(mode="after")
    def _refuse_to_run_unlocked(self) -> Self:
        """Fail at startup rather than serve the Diary to whoever asks first."""
        missing = [name for name in ("pin", "session_secret") if not getattr(self, name).strip()]
        if missing:
            raise ValueError(
                f"{' and '.join(name.upper() for name in missing)} must be set. "
                "Copy .env.example to .env and fill them in."
            )
        return self
