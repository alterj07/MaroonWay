"""Semester arithmetic.

"The past 2 semesters" has to be derived from the data, not from today's date:
an RMP scrape run in December and one run in June should summarise the same
reviews if the reviews have not changed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import total_ordering

SPRING, SUMMER, FALL = "spring", "summer", "fall"
SEASON_ORDER = {SPRING: 0, SUMMER: 1, FALL: 2}
#: A&M-style numeric term codes end in a season digit plus a campus digit:
#: 202511 is spring 2025, 202521 summer, 202531 fall.
SEASON_CODES = {"1": SPRING, "2": SUMMER, "3": FALL}


@total_ordering
@dataclass(frozen=True, slots=True)
class Term:
    year: int
    season: str

    def __post_init__(self) -> None:
        if self.season not in SEASON_ORDER:
            raise ValueError(f"unknown season: {self.season!r}")

    @property
    def sort_index(self) -> int:
        return self.year * 10 + SEASON_ORDER[self.season]

    @property
    def label(self) -> str:
        return f"{self.season.capitalize()} {self.year}"

    def __lt__(self, other: "Term") -> bool:
        return self.sort_index < other.sort_index

    def previous(self) -> "Term":
        rank = SEASON_ORDER[self.season] - 1
        if rank < 0:
            return Term(self.year - 1, FALL)
        return Term(self.year, next(s for s, r in SEASON_ORDER.items() if r == rank))

    def bounds(self) -> tuple[datetime, datetime]:
        """Half-open [start, end) in UTC."""
        if self.season == SPRING:
            return (
                datetime(self.year, 1, 1, tzinfo=timezone.utc),
                datetime(self.year, 6, 1, tzinfo=timezone.utc),
            )
        if self.season == SUMMER:
            return (
                datetime(self.year, 6, 1, tzinfo=timezone.utc),
                datetime(self.year, 8, 1, tzinfo=timezone.utc),
            )
        return (
            datetime(self.year, 8, 1, tzinfo=timezone.utc),
            datetime(self.year + 1, 1, 1, tzinfo=timezone.utc),
        )


def term_of(moment: datetime) -> Term:
    """Which semester a review date falls in."""
    month = moment.month
    if month <= 5:
        return Term(moment.year, SPRING)
    if month <= 7:
        return Term(moment.year, SUMMER)
    return Term(moment.year, FALL)


def recent_terms(moments: Iterable[datetime], count: int = 2) -> list[Term]:
    """The ``count`` most recent semesters actually present in the data, newest first."""
    seen = {term_of(m) for m in moments if m is not None}
    return sorted(seen, reverse=True)[:count]


def window_of(terms: Iterable[Term]) -> tuple[datetime, datetime] | None:
    """The [start, end) spanning several terms -- stored on each summary row."""
    ordered = sorted(terms)
    if not ordered:
        return None
    return (ordered[0].bounds()[0], ordered[-1].bounds()[1])


def parse_term(value: str | int | None) -> Term | None:
    """Parse ``202531``, ``"Fall 2025"``, ``"2025 FALL"``, or ``"FA25"``.

    The grades CSV's term column could be any of these; returns ``None`` rather
    than guessing when it is something else.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if (digits := re.fullmatch(r"(\d{4})([123])\d?", text)) is not None:
        return Term(int(digits.group(1)), SEASON_CODES[digits.group(2)])

    lowered = text.lower()
    season = None
    for name in (FALL, SPRING, SUMMER):
        if name in lowered or lowered.startswith(name[:2]):
            season = name
            break
    year_match = re.search(r"(20\d{2}|19\d{2})", text)
    if season and year_match:
        return Term(int(year_match.group(1)), season)
    # "FA25" has no word boundary before the digits, so anchor to the end.
    if season and (short := re.search(r"(\d{2})\s*$", text)):
        return Term(2000 + int(short.group(1)), season)
    return None
