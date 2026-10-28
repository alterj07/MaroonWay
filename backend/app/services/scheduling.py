"""Building conflict-free schedules.

The planning doc's one hard requirement: **at least 20 minutes between
classes**, raisable by the student. Everything else here serves that or the
ranking rule next to it -- RMP score first, then difficulty.

Pure logic, no database and no I/O, so the awkward cases (a class that ends
exactly when the next begins, back-to-back across a midday gap, an online
section that cannot clash with anything) are all testable directly.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The doc's floor. A student may raise it; nothing may lower it below this
#: without saying so explicitly.
DEFAULT_MIN_GAP_MINUTES = 20

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
#: A&M writes meeting patterns as MWF / TR / MW, where R is Thursday.
DAY_LETTERS = {"M": "MON", "T": "TUE", "W": "WED", "R": "THU", "F": "FRI", "S": "SAT", "U": "SUN"}
DAY_ALIASES = {
    "MONDAY": "MON", "TUESDAY": "TUE", "WEDNESDAY": "WED", "THURSDAY": "THU",
    "FRIDAY": "FRI", "SATURDAY": "SAT", "SUNDAY": "SUN",
    "TH": "THU", "TUES": "TUE", "THURS": "THU",
}
_TIME_RE = re.compile(r"^\s*(\d{1,2}):?(\d{2})\s*([APap]\.?[Mm]\.?)?\s*$")


def parse_days(value: Any) -> tuple[str, ...]:
    """``"MWF"`` / ``"TR"`` / ``"Mon,Wed"`` / ``["MON"]`` -> day codes, in week order."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        found = {d for item in value for d in parse_days(item)}
        return tuple(day for day in DAYS if day in found)

    text = str(value).strip().upper()
    if not text:
        return ()

    found: set[str] = set()
    for chunk in re.split(r"[,/;\s]+", text):
        if not chunk:
            continue
        if chunk in DAYS:
            found.add(chunk)
        elif chunk in DAY_ALIASES:
            found.add(DAY_ALIASES[chunk])
        else:
            # A compact pattern such as MWF or TR.
            letters = [DAY_LETTERS[c] for c in chunk if c in DAY_LETTERS]
            if len(letters) == len(chunk):
                found.update(letters)
    return tuple(day for day in DAYS if day in found)


def parse_time(value: Any) -> int | None:
    """``"09:10"`` / ``"0910"`` / ``"1:25 PM"`` -> minutes since midnight."""
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 0 <= value <= 24 * 60 else None

    match = _TIME_RE.match(str(value))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    suffix = (match.group(3) or "").replace(".", "").upper()
    if suffix and not 1 <= hour <= 12:
        return None
    if suffix == "PM" and hour < 12:
        hour += 12
    elif suffix == "AM" and hour == 12:
        hour = 0
    if not (0 <= hour <= 24 and 0 <= minute < 60) or (hour == 24 and minute != 0):
        return None
    return hour * 60 + minute


def format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True, slots=True)
class Meeting:
    day: str
    start: int  # minutes since midnight
    end: int
    building: str | None = None
    room: str | None = None

    @property
    def label(self) -> str:
        where = " ".join(p for p in (self.building, self.room) if p)
        return f"{self.day} {format_time(self.start)}-{format_time(self.end)}" + (
            f" {where}" if where else ""
        )


def parse_meetings(raw: Any) -> tuple[Meeting, ...]:
    """Read the ``sections.meets`` JSONB into meetings, dropping unusable rows.

    A section with no parseable meeting may be asynchronous online or may have
    missing times. Its explicit delivery mode determines whether it is usable.
    """
    if not raw:
        return ()
    entries = raw if isinstance(raw, (list, tuple)) else [raw]
    meetings: list[Meeting] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        start = parse_time(entry.get("start") or entry.get("start_time") or entry.get("begin"))
        end = parse_time(entry.get("end") or entry.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        for day in parse_days(entry.get("day") or entry.get("days")):
            meetings.append(
                Meeting(
                    day=day,
                    start=start,
                    end=end,
                    building=(entry.get("building") or None),
                    room=(entry.get("room") or None),
                )
            )
    return tuple(sorted(meetings, key=lambda m: (DAYS.index(m.day), m.start)))


@dataclass(frozen=True, slots=True)
class Section:
    """One offering a student could register for."""

    section_id: int
    course_id: int
    code: str  # CSCE121
    section_code: str  # 501
    term: str
    instructor_id: int | None = None
    instructor_name: str | None = None
    campus: str | None = None
    delivery: str | None = None  # F2F | WEB | HYBRID
    honors: bool = False
    seats_open: int | None = None
    meetings: tuple[Meeting, ...] = ()
    # From instructor_course_scores; the ranking rule reads these.
    adj_rating: float | None = None
    adj_difficulty: float | None = None
    adj_gpa: float | None = None
    #: Share of students who earned an A, 0-1.
    pct_a: float | None = None
    #: Reviews behind the rating: for this course, and for the instructor
    #: overall. A rating with few reviews has been shrunk toward the average,
    #: and that shrinkage is invisible in the number that comes out.
    class_reviews: int = 0
    professor_reviews: int = 0
    #: Other sections of this course at exactly these times, taught by someone
    #: else. A choice the student has that the timetable does not show.
    same_time_alternatives: int = 0

    @property
    def is_online(self) -> bool:
        """Explicitly remote; synchronous online classes can still have meetings."""
        return self.delivery == "WEB"

    @property
    def is_schedulable(self) -> bool:
        """Known meetings, or an explicitly online section with no fixed time."""
        return bool(self.meetings) or self.is_online

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(m.day for m in self.meetings))


@dataclass(frozen=True, slots=True)
class Availability:
    """When a student is willing to be in class."""

    earliest: int | None = None  # minutes since midnight
    latest: int | None = None
    #: Days the student refuses, e.g. {"FRI"} for no Friday classes.
    excluded_days: frozenset[str] = frozenset()

    def allows(self, meeting: Meeting) -> bool:
        if meeting.day in self.excluded_days:
            return False
        if self.earliest is not None and meeting.start < self.earliest:
            return False
        if self.latest is not None and meeting.end > self.latest:
            return False
        return True

    def allows_section(self, section: Section) -> bool:
        return section.is_schedulable and all(self.allows(m) for m in section.meetings)


@dataclass(frozen=True, slots=True)
class Lock:
    """A choice the student made themselves, for one course.

    Everything here is a hard filter, which is the whole point: a preference
    Jev inferred is a ranking signal because guessing wrong should not empty
    the results, but a student who pinned a section meant it. If a lock leaves
    a course with nothing, that is an answer to report, not one to relax.

    Unset fields do not constrain. Unknown data on a section does not fail a
    filter it says nothing about -- a section with no recorded campus is not
    excluded by a campus lock, for the same reason the SQL filters are
    permissive about nulls.
    """

    section_code: str | None = None
    instructor_id: int | None = None
    instructor_name: str | None = None
    honors: bool | None = None
    delivery: str | None = None
    campus: str | None = None
    #: Days the class may meet on. A section meeting on any other day is out.
    days: frozenset[str] = frozenset()
    earliest: int | None = None  # minutes since midnight
    latest: int | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.section_code,
                self.instructor_id is not None,
                self.instructor_name,
                self.honors is not None,
                self.delivery,
                self.campus,
                self.days,
                self.earliest is not None,
                self.latest is not None,
            )
        )

    def allows(self, section: Section) -> bool:
        if self.section_code and section.section_code != self.section_code:
            return False
        if self.instructor_id is not None and section.instructor_id != self.instructor_id:
            return False
        if self.instructor_name:
            name = (section.instructor_name or "").strip().casefold()
            if name != self.instructor_name.strip().casefold():
                return False
        if self.honors is not None and section.honors != self.honors:
            return False
        if self.delivery and section.delivery and section.delivery != self.delivery:
            return False
        if self.campus and section.campus and section.campus != self.campus:
            return False
        if self.days and not all(m.day in self.days for m in section.meetings):
            return False
        if self.earliest is not None and any(m.start < self.earliest for m in section.meetings):
            return False
        if self.latest is not None and any(m.end > self.latest for m in section.meetings):
            return False
        return True

    def describe(self) -> str:
        """The lock in the student's own terms, for an error they can act on."""
        parts: list[str] = []
        if self.section_code:
            parts.append(f"section {self.section_code}")
        if self.instructor_name:
            parts.append(self.instructor_name)
        elif self.instructor_id is not None:
            parts.append(f"instructor {self.instructor_id}")
        if self.honors is not None:
            parts.append("honors" if self.honors else "non-honors")
        if self.delivery:
            parts.append({"WEB": "online", "F2F": "in person"}.get(self.delivery, self.delivery))
        if self.campus:
            parts.append(self.campus)
        if self.days:
            parts.append("/".join(d for d in DAYS if d in self.days))
        if self.earliest is not None:
            parts.append(f"from {format_time(self.earliest)}")
        if self.latest is not None:
            parts.append(f"until {format_time(self.latest)}")
        return ", ".join(parts) or "no constraints"


def apply_locks(
    candidates: Mapping[str, Sequence[Section]],
    locks: Mapping[str, Lock],
) -> tuple[dict[str, list[Section]], list[str]]:
    """Narrow each course's pool to what its lock allows.

    Returns the narrowed pools and the courses a lock emptied. An emptied pool
    is reported rather than silently dropped or silently ignored: both would
    leave the student looking at a result that does not mean what they think.
    """
    narrowed: dict[str, list[Section]] = {}
    impossible: list[str] = []
    for code, sections in candidates.items():
        lock = locks.get(code)
        if lock is None or lock.is_empty:
            narrowed[code] = list(sections)
            continue
        allowed = [s for s in sections if lock.allows(s)]
        if not allowed:
            impossible.append(f"no section of {code} matches what you pinned ({lock.describe()})")
        narrowed[code] = allowed
    return narrowed, impossible


def gap_between(first: Meeting, second: Meeting) -> int | None:
    """Minutes between two meetings on the same day, or ``None`` if different days.

    Negative means they overlap.
    """
    if first.day != second.day:
        return None
    earlier, later = (first, second) if first.start <= second.start else (second, first)
    return later.start - earlier.end


def clash(left: Section, right: Section, min_gap: int = DEFAULT_MIN_GAP_MINUTES) -> str | None:
    """Why these two sections cannot both be taken, or ``None`` if they can."""
    for section in (left, right):
        if not section.is_schedulable:
            return f"meeting times are missing for {section.code}; conflicts cannot be verified"
    # A&M teaches the same catalog numbers at College Station, Galveston and in
    # Qatar. Two in-person sections on different campuses are not a timetable
    # conflict but they are still impossible to attend, and no gap is long
    # enough to bridge them. Explicitly online sections require no campus
    # travel, but any synchronous meetings must still pass the time checks.
    if (
        left.campus
        and right.campus
        and left.campus != right.campus
        and not left.is_online
        and not right.is_online
    ):
        return (
            f"{left.code} is at {left.campus} and {right.code} is at "
            f"{right.campus}; a student cannot attend both"
        )

    for first in left.meetings:
        for second in right.meetings:
            gap = gap_between(first, second)
            if gap is None:
                continue
            if gap < 0:
                return f"{left.code} and {right.code} overlap on {first.day}"
            if gap < min_gap:
                return (
                    f"only {gap} min between {left.code} and {right.code} on "
                    f"{first.day}, less than the {min_gap} min required"
                )
    return None


@dataclass(frozen=True, slots=True)
class Schedule:
    sections: tuple[Section, ...]
    #: Smallest gap between any two classes, in minutes. None when nothing
    #: shares a day (every section online, or one class a day).
    tightest_gap: int | None
    mean_rating: float
    mean_difficulty: float
    mean_gpa: float | None
    mean_pct_a: float | None
    earliest_start: int | None
    days_on_campus: int
    #: Minutes on campus with nothing scheduled -- the waiting a student does
    #: between their own classes, summed over the week. Two schedules can be
    #: identical on every professor and still differ by hours of this.
    idle_minutes: int

    @property
    def sort_key(self) -> tuple[float, float]:
        """The doc's rule: RMP score first, then difficulty."""
        return (-self.mean_rating, self.mean_difficulty)


def _mean(values: Sequence[float]) -> float | None:
    numbers = [v for v in values if v is not None]
    return sum(numbers) / len(numbers) if numbers else None


def summarize(sections: Sequence[Section], *, default_rating: float = 3.5) -> Schedule:
    """Describe a chosen set of sections.

    Every measure about *time* counts only the sections a student physically
    attends. An online class is not a reason to be on campus: it does not make
    a Tuesday a day on campus, it cannot be the early start someone asked to
    avoid, and the hours around it are not time spent waiting between classes.
    Counting it was quietly answering a different question from the one the
    student asked.

    Conflicts are the exception and are checked over every section in
    ``clash``: a synchronous online lecture still occupies the hour it runs in.
    """
    gaps: list[int] = []
    for index, left in enumerate(sections):
        for right in sections[index + 1 :]:
            for first in left.meetings:
                for second in right.meetings:
                    gap = gap_between(first, second)
                    if gap is not None:
                        gaps.append(gap)

    on_campus = [s for s in sections if not s.is_online]
    starts = [m.start for s in on_campus for m in s.meetings]

    # Per day: the span from the first class to the last, less the time
    # actually spent in class.
    idle = 0
    by_day: dict[str, list[Meeting]] = {}
    for section in on_campus:
        for meeting in section.meetings:
            by_day.setdefault(meeting.day, []).append(meeting)
    for meetings in by_day.values():
        span = max(m.end for m in meetings) - min(m.start for m in meetings)
        idle += span - sum(m.end - m.start for m in meetings)

    return Schedule(
        sections=tuple(sections),
        tightest_gap=min(gaps) if gaps else None,
        mean_rating=_mean([s.adj_rating for s in sections]) or default_rating,
        mean_difficulty=_mean([s.adj_difficulty for s in sections]) or 3.0,
        mean_gpa=_mean([s.adj_gpa for s in sections]),
        mean_pct_a=_mean([s.pct_a for s in sections]),
        earliest_start=min(starts) if starts else None,
        days_on_campus=len({m.day for s in on_campus for m in s.meetings}),
        idle_minutes=idle,
    )


class SearchLimitExceeded(RuntimeError):
    """An incomplete search is not proof that a schedule is impossible."""


def generate(
    candidates: Mapping[str, Sequence[Section]],
    *,
    min_gap: int = DEFAULT_MIN_GAP_MINUTES,
    availability: Availability | None = None,
    limit: int = 10,
    max_combinations: int = 200_000,
) -> list[Schedule]:
    """Every conflict-free way to take one section of each course, best first.

    Depth-first with pruning: a partial schedule that already breaks the gap
    rule is abandoned rather than completed and discarded, which is what keeps
    a dozen courses with a dozen sections each tractable.

    The budget counts attempted section choices, including rejected branches.
    At exhaustion, return valid results found so far or explain the incomplete
    search; an unfinished search must not claim that no schedule exists.
    """
    availability = availability or Availability()
    courses = sorted(candidates)
    if not courses:
        return []

    # Filter first, so an impossible course is obvious and the search is smaller.
    pools: list[list[Section]] = []
    for code in courses:
        allowed = [s for s in candidates[code] if availability.allows_section(s)]
        if not allowed:
            return []  # this course cannot be taken within the stated availability
        pools.append(allowed)

    results: list[Schedule] = []
    examined = 0
    exhausted = False

    def walk(index: int, chosen: list[Section]) -> None:
        nonlocal examined, exhausted
        if index == len(pools):
            results.append(summarize(chosen))
            return
        for section in pools[index]:
            if examined >= max_combinations:
                exhausted = True
                return
            examined += 1
            if any(clash(section, picked, min_gap) for picked in chosen):
                continue
            chosen.append(section)
            walk(index + 1, chosen)
            chosen.pop()

    walk(0, [])
    if exhausted and not results:
        raise SearchLimitExceeded("Search limit reached. Try fewer courses or narrower time filters; a schedule may still exist.")
    results.sort(key=lambda schedule: schedule.sort_key)
    return results[:limit]


def describe_failure(
    candidates: Mapping[str, Sequence[Section]],
    *,
    min_gap: int = DEFAULT_MIN_GAP_MINUTES,
    availability: Availability | None = None,
) -> str:
    """Say why nothing could be built, so the UI can explain rather than shrug."""
    availability = availability or Availability()
    for code, sections in sorted(candidates.items()):
        if not sections:
            return f"no sections on record for {code}"
        if not any(s.is_schedulable for s in sections):
            return f"meeting times are missing for {code}; conflicts cannot be verified"
        if not any(availability.allows_section(s) for s in sections):
            return f"every section of {code} falls outside your availability"

    # Report the near miss: of the pairs that cannot be combined, the one whose
    # best case comes closest to working. That tells the student which number to
    # relax, instead of naming whichever conflict a set happened to yield first.
    best: tuple[int, str] | None = None
    codes = sorted(candidates)
    for i, left_code in enumerate(codes):
        for right_code in codes[i + 1 :]:
            lefts = [s for s in candidates[left_code] if availability.allows_section(s)]
            rights = [s for s in candidates[right_code] if availability.allows_section(s)]
            if any(clash(a, b, min_gap) is None for a in lefts for b in rights):
                continue  # this pair is fine; the problem lies elsewhere
            gaps = [
                gap
                for a in lefts
                for b in rights
                for first in a.meetings
                for second in b.meetings
                if (gap := gap_between(first, second)) is not None
            ]
            widest = max(gaps) if gaps else None
            if widest is None:
                message = f"{left_code} and {right_code} cannot be combined"
            elif widest < 0:
                message = f"every section of {left_code} overlaps every section of {right_code}"
            else:
                message = (
                    f"{left_code} and {right_code} cannot be combined: the closest any "
                    f"two of their sections come is {widest} min, less than the "
                    f"{min_gap} min required"
                )
            if best is None or (widest if widest is not None else -1) > best[0]:
                best = ((widest if widest is not None else -1), message)

    if best is not None:
        return best[1]
    return "no conflict-free combination exists for those courses"


#: Words that pass for a surname but are just how students write. A section
#: taught by someone named Young must not be pinned by "I want young classes".
_NOT_A_SURNAME = frozenset(
    {
        "THE", "AND", "FOR", "NOT", "WITH", "WANT", "WANTS", "LIKE", "NEED", "PLEASE",
        "CLASS", "CLASSES", "COURSE", "COURSES", "TEACHER", "TEACHERS", "PROF",
        "PROFESSOR", "PROFESSORS", "INSTRUCTOR", "SECTION", "SCHEDULE", "MORNING",
        "MORNINGS", "AFTERNOON", "EVENING", "EARLY", "LATE", "EASY", "EASIER", "HARD",
        "GOOD", "BEST", "BETTER", "GREAT", "NICE", "ONLINE", "HONORS", "CAMPUS",
        "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY",
        "STAFF", "TBA", "TBD",
    }
)


def _surnames(full_name: str) -> set[str]:
    """The parts of a name worth searching a sentence for.

    Initials and two-letter fragments are dropped: they match far too much, and
    a student writing "I want Lee" means the surname, not the L of someone else.
    """
    parts = re.split(r"[^A-Za-z]+", full_name.upper())
    return {p for p in parts if len(p) >= 3 and p not in _NOT_A_SURNAME}


def instructor_wishes(
    wants: str | None,
    candidates: Mapping[str, Sequence[Section]],
) -> tuple[dict[str, Lock], list[str]]:
    """Professors the student named, pinned to the courses they actually teach.

    "I want Chupp for POLS207" is not a preference to weigh against a rating --
    it is a choice, and weighing it meant the schedule came back taught by
    someone else with no explanation. Nothing here is inferred by a model: a
    name is pinned only when it matches an instructor already in that course's
    pool, so a sentence can never ask for a section that does not exist.

    Returns the locks, and notes for names that matched nobody or matched more
    than one person in the same course, which are both things to say out loud
    rather than resolve by guessing.
    """
    text = (wants or "").strip()
    if not text:
        return {}, []

    haystack = text.upper()
    locks: dict[str, Lock] = {}
    notes: list[str] = []

    for code in sorted(candidates):
        matched: dict[int, str] = {}
        for section in candidates[code]:
            if section.instructor_id is None or not section.instructor_name:
                continue
            for surname in _surnames(section.instructor_name):
                if re.search(rf"\b{re.escape(surname)}\b", haystack):
                    matched[section.instructor_id] = section.instructor_name
                    break
        if len(matched) == 1:
            instructor_id, name = next(iter(matched.items()))
            locks[code] = Lock(instructor_id=instructor_id)
            notes.append(f"pinned {name} for {code}, as you asked")
        elif len(matched) > 1:
            names = ", ".join(sorted(matched.values()))
            notes.append(
                f"more than one instructor of {code} matches the name you gave "
                f"({names}), so none was pinned -- say which in the course panel"
            )

    # A name that matched nobody. Said out loud rather than ignored: a student
    # who asks for Chupp and is handed Thornton with no comment has no way to
    # tell whether Chupp was unavailable or simply not understood.
    known = {
        surname
        for sections in candidates.values()
        for section in sections
        if section.instructor_name
        for surname in _surnames(section.instructor_name)
    }
    # Course codes are capitalised too, and are not people.
    course_words = {
        word
        for code in candidates
        for word in re.split(r"(?<=[A-Za-z])(?=\d)", code.upper())
        if word
    }
    for token in re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text):
        upper = token.upper()
        if upper in known or upper in _NOT_A_SURNAME or upper in course_words:
            continue
        notes.append(
            f"no instructor named {token} teaches any of these courses this term, "
            "so nothing was pinned for that"
        )
    return locks, notes
