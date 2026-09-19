"""The current time, injected rather than read ambiently.

This exists so tests can place themselves on a chosen evening — an age one day
before a birthday, an Answer at 01:30 — and is not a general-purpose abstraction:
there is exactly one production implementation.
"""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from fastapi import Request


class Clock(Protocol):
    def now(self) -> datetime:
        """The current moment, in the family's timezone."""
        ...


class SystemClock:
    def __init__(self, timezone: str) -> None:
        self._timezone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._timezone)


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock
