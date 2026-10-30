"""Deciding which RateMyProfessors profile is which A&M instructor.

The name alone cannot do this. Among 4,429 instructors teaching at College
Station in Fall 2026 there are only 3 exact full-name collisions, but 208
collisions on surname plus first initial -- "KIM J" is ten different people,
"WANG X" is seven. The grade reports give us only that abbreviated form, which
is why matching on it left most instructors with no rating at all.

Two things fix it. A&M's public class search carries each instructor's full
name and a stable person id, so identity on our side no longer depends on
RateMyProfessors at all; and it lists what each of them actually teaches,
which is the evidence that separates one Kim from another.

Subject affinity is the heart of it. A professor with five English sections is
not the one teaching gender studies, even where the names agree exactly. It is
measured as a histogram intersection rather than a set overlap, so a professor
who teaches mostly CSCE and one cross-listed ENGR section reads as a CSCE
professor and is still allowed to match a profile showing a little ENGR. A set
overlap would score those two subjects equally and lose the distinction the
whole thing turns on.

Nothing here does I/O. Who a professor is should be decidable from the records
in front of you, and testable without a network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

#: Name fragments that are titles or ornaments rather than names.
_ORNAMENTS = frozenset({"JR", "SR", "II", "III", "IV", "DR", "PROF", "PROFESSOR", "MR", "MRS", "MS"})

#: A&M marks the instructor of record "(P)" and others "(S)" in the public
#: class search. Neither is part of anybody's name.
_ROLE_MARK = re.compile(r"\s*\((?:P|S)\)\s*$")

#: Particles that belong to the surname that follows them. Without these,
#: "Jan van der Berg" reads as a Mr Berg and stops agreeing with the grade
#: reports' "VAN DER BERG J", which is the same person spelled the other way.
#: Normalisation has already upper-cased everything, so the usual trick of
#: spotting a lower-case particle is not available.
_PARTICLES = frozenset(
    {"VAN", "VON", "DER", "DEN", "DE", "DEL", "DELLA", "DI", "DA", "DOS", "DU",
     "LA", "LE", "LOS", "BIN", "IBN", "AL", "ST", "TER", "TEN"}
)


def normalize(value: str | None) -> str:
    """Upper-case ASCII letters and single spaces. Accents folded, not dropped."""
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z ]", " ", folded).upper().split())


@dataclass(frozen=True, slots=True)
class Name:
    """A name split the one way that matters: surname, and first given name."""

    surname: str
    given: str

    @property
    def is_initial(self) -> bool:
        """Whether all we have is a first initial -- the weak form."""
        return len(self.given) == 1


def read_name(raw: str | None) -> Name | None:
    """Read any of the three forms we receive, or None if it is not a name.

    "Yum, Ki Hwan K"      A&M public class search, and most registry exports
    "Ki Hwan K. Yum (P)"  the same search's instructor JSON, role marked
    "YUM K"               the grade reports, and all we had before
    """
    text = _ROLE_MARK.sub("", str(raw or ""))
    if "," in text:
        last, _, rest = text.partition(",")
        surname = " ".join(t for t in normalize(last).split() if t not in _ORNAMENTS)
        given = [t for t in normalize(rest).split() if t not in _ORNAMENTS]
        return Name(surname, given[0]) if surname and given else None

    tokens = [t for t in normalize(text).split() if t not in _ORNAMENTS]
    if len(tokens) < 2:
        return None
    if len(tokens[-1]) == 1:
        # "YUM K": the trailing letter is the initial, the rest is the surname.
        return Name(" ".join(tokens[:-1]), tokens[-1])
    # "Ki Hwan K. Yum": the trailing token is the surname and the leading one
    # the given name; middle names are dropped rather than guessed at. A
    # surname may reach back over its particles -- "Jan van der Berg" is a Mr
    # van der Berg -- but never so far as to swallow the given name.
    start = len(tokens) - 1
    while start > 1 and tokens[start - 1] in _PARTICLES:
        start -= 1
    return Name(" ".join(tokens[start:]), tokens[0])


def names_agree(ours: Name, theirs: Name) -> bool:
    """Whether two names can belong to one person.

    Surnames must match outright. Given names match when one is a prefix of the
    other, which is exactly the initial-against-full-name case and nothing
    looser: JUSTIN and JUSTINE are two people and a fuzzy rule would merge them.
    """
    if not ours.surname or ours.surname != theirs.surname:
        return False
    a, b = ours.given, theirs.given
    if not a or not b:
        return False
    return b.startswith(a) if len(a) <= len(b) else a.startswith(b)


def subject_of(course_code: str | None) -> str:
    """"CSCE 121", "csce121", "CSCE121H" -> "CSCE"."""
    letters = re.match(r"\s*([A-Za-z]+)", str(course_code or ""))
    return letters.group(1).upper() if letters else ""


def subject_weights(courses: Mapping[str, int]) -> dict[str, float]:
    """Course counts -> the share of someone's teaching each subject is."""
    totals: dict[str, float] = {}
    for code, count in courses.items():
        subject = subject_of(code)
        if subject:
            totals[subject] = totals.get(subject, 0.0) + max(0, count)
    grand = sum(totals.values())
    return {s: n / grand for s, n in totals.items()} if grand else {}


def subject_affinity(ours: Mapping[str, int], theirs: Mapping[str, int]) -> float:
    """How alike two people's teaching is, 0-1.

    Histogram intersection: the overlap of two distributions rather than of two
    sets. Someone who is four-fifths CSCE and one-fifth ENGR scores high
    against a profile with the same balance and lower against one that is
    wholly ENGR, which is the distinction a set overlap throws away.

    Returns 0.0 when either side has nothing on record. That is "no evidence",
    not "no match", and callers must not read it as disagreement.
    """
    left, right = subject_weights(ours), subject_weights(theirs)
    if not left or not right:
        return 0.0
    return sum(min(share, right.get(subject, 0.0)) for subject, share in left.items())


@dataclass(frozen=True, slots=True)
class Person:
    """An instructor, as A&M identifies them."""

    #: The stable A&M person id. Verified across Fall 2026 and Spring 2027:
    #: no id carried two names, and all 3,619 ids in both terms kept the same
    #: one. This is what instructors are keyed on, never an RMP id -- so a
    #: change at RateMyProfessors cannot disturb anyone's schedule.
    person_id: int
    full_name: str
    #: Course code -> sections taught, from the class schedule.
    courses: Mapping[str, int] = field(default_factory=dict)
    campus: str | None = None

    @property
    def name(self) -> Name | None:
        return read_name(self.full_name)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A RateMyProfessors profile the person might be."""

    rmp_id: int
    full_name: str
    department: str | None = None
    #: Course code -> ratings mentioning it, from RMP's courseCodes.
    courses: Mapping[str, int] = field(default_factory=dict)
    campus: str | None = None
    rating_count: int = 0

    @property
    def name(self) -> Name | None:
        return read_name(self.full_name)


#: How far ahead the winner must be before we believe it. Two profiles that
#: score within this of each other are not a match, they are a coin toss.
MARGIN = 0.15

#: Affinity below which a contested name is not resolved at all. A namesake
#: decided on a rounding error is worse than no rating.
MIN_AFFINITY = 0.2


@dataclass(frozen=True, slots=True)
class Resolution:
    """Who we think this is, and what the decision rested on."""

    person_id: int
    rmp_id: int | None
    #: "unique" | "affinity" | "ambiguous" | "no_candidates" | "unreadable_name"
    basis: str
    confidence: float
    reason: str
    runner_up: int | None = None

    @property
    def linked(self) -> bool:
        return self.rmp_id is not None


def resolve(person: Person, candidates: list[Candidate]) -> Resolution:
    """Link one instructor to one RMP profile, or explain why not.

    Order matters. A name that fits exactly one profile is that profile --
    asking subject affinity to confirm it would throw away the 97% of cases
    where the name is already decisive, which is the mistake the old matcher
    made with departments. Affinity is brought in only when several profiles
    answer to the same name, which is where it earns its keep: "KIM J" is ten
    people, and they teach ten different things.
    """
    ours = person.name
    if ours is None:
        return Resolution(person.person_id, None, "unreadable_name", 0.0,
                          f"{person.full_name!r} is not a readable name")

    matching = [
        c for c in candidates
        if (theirs := c.name) is not None
        and names_agree(ours, theirs)
        and (not person.campus or not c.campus or person.campus == c.campus)
    ]
    if not matching:
        return Resolution(person.person_id, None, "no_candidates", 0.0,
                          f"nobody on RateMyProfessors is named {person.full_name}")

    if len(matching) == 1:
        only = matching[0]
        return Resolution(person.person_id, only.rmp_id, "unique", 1.0,
                          f"the only profile named {person.full_name}")

    scored = sorted(
        ((subject_affinity(person.courses, c.courses), c) for c in matching),
        key=lambda pair: (pair[0], pair[1].rating_count),
        reverse=True,
    )
    (best_score, best), (next_score, runner_up) = scored[0], scored[1]

    if best_score < MIN_AFFINITY:
        return Resolution(
            person.person_id, None, "ambiguous", best_score,
            f"{len(matching)} profiles named {person.full_name} and nothing on "
            "record says which of them teaches what you teach",
            runner_up=runner_up.rmp_id,
        )
    if best_score - next_score < MARGIN:
        return Resolution(
            person.person_id, None, "ambiguous", best_score,
            f"{len(matching)} profiles named {person.full_name} teach too much "
            "the same thing to tell apart",
            runner_up=runner_up.rmp_id,
        )
    return Resolution(
        person.person_id, best.rmp_id, "affinity", best_score,
        f"of {len(matching)} profiles named {person.full_name}, this one teaches "
        f"what you teach ({_shared(person, best)})",
        runner_up=runner_up.rmp_id,
    )


def _shared(person: Person, candidate: Candidate) -> str:
    left, right = subject_weights(person.courses), subject_weights(candidate.courses)
    both = sorted(set(left) & set(right), key=lambda s: -min(left[s], right[s]))
    return ", ".join(both[:3]) if both else "no shared subject"
