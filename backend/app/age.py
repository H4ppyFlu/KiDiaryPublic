"""How old the Child was on a given day.

The highest-value derived field in an archive meant to be read years later (ADR-0002),
and the one thing every Answer in the Diary is labelled with — so it is derived from a
date rather than stored, and it says it in German.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, computed_field


class Age(BaseModel):
    model_config = ConfigDict(frozen=True)

    years: int
    months: int

    @computed_field
    @property
    def label(self) -> str:
        """As the Diary shows it: "2 Jahre, 4 Monate", "1 Jahr, 1 Monat", "3 Jahre"."""
        parts = []
        if self.years:
            parts.append(f"{self.years} {'Jahr' if self.years == 1 else 'Jahre'}")
        # A round number of years drops the months; a Child under one month old still
        # needs something to show.
        if self.months or not parts:
            parts.append(f"{self.months} {'Monat' if self.months == 1 else 'Monate'}")
        return ", ".join(parts)


def age_on(birthdate: date, day: date) -> Age:
    """A month turns on the day of the month the Child was born, a year on the birthday.

    A Child born on the 31st therefore turns a month on the 1st in the months that have
    no 31st, which is how everyone counts it out loud.
    """
    months = (day.year - birthdate.year) * 12 + day.month - birthdate.month
    if day.day < birthdate.day:
        months -= 1
    # A birthdate in the future is a mistake in configuration rather than a Child to
    # describe; it reads as newborn rather than as a negative age.
    years, months = divmod(max(months, 0), 12)
    return Age(years=years, months=months)
