"""Matching instructor names across two sources that do not agree.

The grades CSV and RateMyProfessors will not spell the same person the same way:
``"DOE, JOHN M"`` vs ``"John Doe"``, suffixes, accents, hyphenated surnames,
reversed order. This is the likeliest source of *wrong data* in MaroonWay -- not
a crash, a silently mismatched professor -- so every decision here is recorded
with its method and confidence in the ``name_links`` table, and anything below
the floor is written to a review file instead of being guessed at.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

try:  # rapidfuzz is the real implementation; difflib keeps tests runnable without it.
    from rapidfuzz import fuzz as _fuzz

    _BACKEND = "rapidfuzz"
except ModuleNotFoundError:  # pragma: no cover - exercised only without the dep
    _fuzz = None
    _BACKEND = "difflib"

T = TypeVar("T")

#: Dropped wherever they appear.
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "dds", "edd"})
#: Dropped only when leading.
TITLES = frozenset({"dr", "prof", "professor", "mr", "mrs", "ms", "mx"})

#: Below this, a fuzzy match is not a match.
DEFAULT_FLOOR = 88.0


def _fold(raw: str) -> str:
    decomposed = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_tokens(raw: str | None) -> list[str]:
    """Lowercase name parts, with titles, suffixes, and middle initials removed.

    ``"DOE, JOHN M."`` and ``"Dr. John Doe Jr."`` both reduce to
    ``["john", "doe"]``.
    """
    if not raw:
        return []
    text = _fold(raw)
    for ch in ".,;_-'\"()":
        text = text.replace(ch, " " if ch in ".,;_-" else "")
    # "Doe, John M" arrives surname-first; swap so the plain form reads naturally.
    if "," in raw:
        surname, _, rest = _fold(raw).partition(",")
        text = f"{rest} {surname}"
        for ch in ".,;_-'\"()":
            text = text.replace(ch, " " if ch in ".,;_-" else "")
    tokens = [t for t in text.lower().split() if t]
    while tokens and tokens[0] in TITLES:
        tokens.pop(0)
    tokens = [t for t in tokens if t not in SUFFIXES]
    # Single letters are middle initials; one source has them, the other rarely does.
    tokens = [t for t in tokens if len(t) > 1]
    return tokens


def normalize_name(raw: str | None) -> str:
    """A readable normalized form, e.g. ``"john doe"``."""
    return " ".join(name_tokens(raw))


def canonical_key(raw: str | None) -> str:
    """An order-insensitive exact-match key, e.g. ``"doe john"``.

    Sorting the tokens means ``"DOE JOHN"`` (the CSV's surname-first habit, with
    no comma to reveal it) and ``"John Doe"`` collide on purpose.
    """
    return " ".join(sorted(name_tokens(raw)))


def similarity(left: str, right: str) -> float:
    """0-100 similarity, order-insensitive."""
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.token_set_ratio(a, b))
    from difflib import SequenceMatcher

    return SequenceMatcher(None, canonical_key(left), canonical_key(right)).ratio() * 100.0


@dataclass(frozen=True, slots=True)
class NameMatch:
    value: Any
    matched_name: str
    score: float
    method: str  # "exact" | "fuzzy:<backend>"

    @property
    def is_exact(self) -> bool:
        return self.method == "exact"


def match_name(
    target: str,
    candidates: Mapping[str, T],
    *,
    floor: float = DEFAULT_FLOOR,
) -> NameMatch | None:
    """Find ``target`` among ``candidates`` (keyed by raw name).

    Exact on :func:`canonical_key` first, then fuzzy above ``floor``. Returns
    ``None`` rather than a bad guess -- callers route those to manual review.
    """
    if not target or not candidates:
        return None

    wanted = canonical_key(target)
    if wanted:
        for name, value in candidates.items():
            if canonical_key(name) == wanted:
                return NameMatch(value, name, 100.0, "exact")

    best: NameMatch | None = None
    for name, value in candidates.items():
        score = similarity(target, name)
        if score >= floor and (best is None or score > best.score):
            best = NameMatch(value, name, score, f"fuzzy:{_BACKEND}")
    return best


def backend() -> str:
    """Which similarity implementation is active -- recorded with each match."""
    return _BACKEND
