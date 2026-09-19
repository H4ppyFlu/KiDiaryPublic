"""The randomness in the draw, injected rather than reached for.

The draw order (ADR-0004) narrows the bank down but rarely to one Prompt: on an evening
where nothing has been answered yet, all twenty are equally eligible and something has
to choose. That something is here, behind a seam, for the same reason `Clock` is — a
test can then corner the rules and get an answer rather than a distribution.

There is exactly one production implementation, and it is not a general-purpose
abstraction. `Dice()` seeds itself from the operating system; a seed is passed only by
the suite.
"""

import random
from collections.abc import Sequence
from typing import Protocol

from fastapi import Request


class Chance(Protocol):
    def pick[T](self, options: Sequence[T]) -> T:
        """One of the options, where nothing in the rules prefers any of them."""
        ...


class Dice:
    def __init__(self, seed: int | None = None) -> None:
        self._rolls = random.Random(seed)

    def pick[T](self, options: Sequence[T]) -> T:
        return self._rolls.choice(options)


def get_chance(request: Request) -> Chance:
    chance: Chance = request.app.state.chance
    return chance
