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
    # Single letters are usually middle initials, and one source has them while
    # the other rarely does -- but A&M's grade reports write instructors as
    # "RODRIGUEZ C", where that letter is the ONLY thing separating two
    # different professors. So drop initials only when enough of the name
    # survives without them.
    words = [t for t in tokens if len(t) > 1]
    return words if len(words) >= 2 else tokens


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
class NameKey:
    """A surname plus a first-name initial: the common ground between
    ``"RODRIGUEZ C"`` (how A&M writes it) and ``"Christopher Rodriguez"``
    (how RateMyProfessors does)."""

    surname: str
    initial: str | None

    @property
    def is_usable(self) -> bool:
        return bool(self.surname and self.initial)


def name_keys(raw: str | None) -> set[NameKey]:
    """Every surname/initial reading of a name.

    A two-word name with no comma is genuinely ambiguous -- ``"DOE JANE"`` could
    be either order -- so both readings are returned and a match on either
    counts.
    """
    tokens = name_tokens(raw)
    words = [t for t in tokens if len(t) > 1]
    letters = [t for t in tokens if len(t) == 1]
    keys: set[NameKey] = set()

    if words and letters:
        # "RODRIGUEZ C": the word is the surname, the letter the initial.
        keys.add(NameKey(words[-1], letters[0]))
        if len(words) > 1:
            keys.add(NameKey(words[0], letters[0]))
    elif len(words) >= 2:
        keys.add(NameKey(words[-1], words[0][0]))   # First Last
        keys.add(NameKey(words[0], words[-1][0]))   # Last First
    elif len(words) == 1:
        keys.add(NameKey(words[0], None))
    return keys


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


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """The result of resolving one name, and the reason for it.

    Ambiguity is reported rather than resolved: two professors who share a
    surname and an initial cannot be told apart from the grade reports alone,
    and guessing would silently attach the wrong ratings to a person.
    """

    match: NameMatch | None
    reason: str  # exact | surname_initial | fuzzy | ambiguous | no_match
    candidates: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.match is not None


def is_initial_form(raw: str | None) -> bool:
    """True for ``"RODRIGUEZ C"``: a surname plus a bare initial.

    This is how A&M's grade reports name instructors, and it is the only case
    where matching on an initial is better evidence than matching on the names
    themselves.
    """
    tokens = name_tokens(raw)
    return any(len(t) == 1 for t in tokens) and any(len(t) > 1 for t in tokens)


def resolve_name(
    target: str,
    candidates: Mapping[str, T],
    *,
    floor: float = DEFAULT_FLOOR,
) -> MatchOutcome:
    """Resolve ``target`` against ``candidates``, reporting how and why.

    Each strategy is applied only where it is actually valid, and anything that
    cannot be told apart comes back as ``ambiguous`` instead of a guess -- the
    wrong professor's ratings on a course page is a worse outcome than a gap.
    """
    if not target or not candidates:
        return MatchOutcome(None, "no_match")

    wanted = canonical_key(target)
    if wanted:
        for name, value in candidates.items():
            if canonical_key(name) == wanted:
                return MatchOutcome(NameMatch(value, name, 100.0, "exact"), "exact")

    if is_initial_form(target):
        target_keys = {key for key in name_keys(target) if key.is_usable}
        hits = [
            (name, value)
            for name, value in candidates.items()
            if target_keys & {k for k in name_keys(name) if k.is_usable}
        ]
        if len(hits) == 1:
            name, value = hits[0]
            return MatchOutcome(
                NameMatch(value, name, 95.0, "surname_initial"), "surname_initial"
            )
        if len(hits) > 1:
            return MatchOutcome(None, "ambiguous", tuple(sorted(n for n, _ in hits)))
        # A readable surname and initial matching nobody is an answer, not a
        # gap. Falling through to fuzzy would let the shared surname alone
        # attach "RODRIGUEZ A" to Christopher Rodriguez.
        return MatchOutcome(None, "initial_mismatch")

    scored = [
        (similarity(target, name), name, value) for name, value in candidates.items()
    ]
    scored = [row for row in scored if row[0] >= floor]
    if not scored:
        return MatchOutcome(None, "no_match")

    top = max(row[0] for row in scored)
    leaders = [row for row in scored if row[0] == top]
    if len(leaders) > 1:
        return MatchOutcome(None, "ambiguous", tuple(sorted(name for _, name, _ in leaders)))

    score, name, value = leaders[0]
    return MatchOutcome(NameMatch(value, name, score, f"fuzzy:{_BACKEND}"), "fuzzy")


def backend() -> str:
    """Which similarity implementation is active -- recorded with each match."""
    return _BACKEND
