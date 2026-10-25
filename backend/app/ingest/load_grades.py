"""Load the grades CSV into Postgres.

    python -m app.ingest.load_grades /path/to/grades.csv --dry-run --limit 500
    python -m app.ingest.load_grades /path/to/grades.csv

Driven entirely by app/ingest/columns.py, so it adapts to the real headers
without edits here. Idempotent: re-running the same file updates rows rather
than duplicating them, which is what makes a half-finished run safe to repeat.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.columns import ColumnMap, resolve_columns, split_course_code
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import course_grades, courses, instructors
from app.services.names import canonical_key, normalize_name
from app.services.terms import parse_term

log = logging.getLogger("ingest.grades")

BATCH_SIZE = 500


@dataclass(slots=True)
class Stats:
    rows_read: int = 0
    rows_loaded: int = 0
    rows_skipped: int = 0
    instructors_seen: int = 0
    courses_seen: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def report(self) -> str:
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(self.skip_reasons.items()))
        return (
            f"read={self.rows_read} loaded={self.rows_loaded} skipped={self.rows_skipped}"
            f" instructors={self.instructors_seen} courses={self.courses_seen}"
            + (f" [{reasons}]" if reasons else "")
        )


def _int(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


#: Campus codes, longest phrase first so "college station" wins over "cs".
#:
#: Galveston and Qatar are A&M campuses in their own right and the grade data
#: covers both; collapsing them into CSTAT or dropping them would quietly
#: mis-file about 1,200 instructor-courses.
_CAMPUS_PHRASES: tuple[tuple[str, str], ...] = (
    ("college station", "CSTAT"),
    ("galveston", "GALV"),
    ("qatar", "QATAR"),
    ("blinn", "BLINN"),
)
#: Whole-word abbreviations. Matched on word boundaries, not as substrings:
#: "cs" occurs inside "PHYSICS", and campus is aliased to columns like
#: campus_basis that can hold a department name.
_CAMPUS_WORDS: dict[str, str] = {
    "cstat": "CSTAT",
    "cs": "CSTAT",
    "main": "CSTAT",
    "tamu": "CSTAT",
    "galv": "GALV",
    "qat": "QATAR",
}


def normalize_campus(value: str | None) -> str | None:
    """Map whatever the CSV says onto a campus code, or nothing."""
    if not value:
        return None
    lowered = value.lower()
    for phrase, code in _CAMPUS_PHRASES:
        if phrase in lowered:
            return code
    for word in re.split(r"[^a-z0-9]+", lowered):
        code = _CAMPUS_WORDS.get(word)
        if code:
            return code
    return None


def _label(value: str | None) -> str | None:
    """A trimmed organisational label, or None when the cell is blank."""
    text = (value or "").strip()
    return text or None


def _bool(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in {"1", "y", "yes", "t", "true", "h", "honors"}


@dataclass(slots=True)
class ParsedRow:
    dept: str
    number: str
    title: str | None
    campus: str | None
    honors: bool
    term: str
    term_year: int | None
    term_season: str | None
    section: str | None
    level: str | None
    college: str | None
    department: str | None
    source_file: str | None
    instructor: str
    gpa: float | None
    enrolled: int | None
    af_total: int | None
    grades: dict[str, int | None]
    source_row: int


def parse_row(row: dict[str, str], cmap: ColumnMap, index: int) -> tuple[ParsedRow | None, str]:
    """One CSV row to one record, or ``(None, reason)``."""
    dept = cmap.get(row, "dept")
    number = cmap.get(row, "number")
    if not (dept and number):
        split = split_course_code(cmap.get(row, "course_code"))
        if split is None:
            return None, "no_course_code"
        dept, number = split

    instructor = cmap.get(row, "instructor")
    if not instructor or not normalize_name(instructor):
        return None, "no_instructor"

    term_raw = cmap.get(row, "term")
    if not term_raw:
        return None, "no_term"
    term = parse_term(term_raw)

    gpa = _float(cmap.get(row, "gpa"))
    grades = {
        "grade_a": _int(cmap.get(row, "grade_a")),
        "grade_b": _int(cmap.get(row, "grade_b")),
        "grade_c": _int(cmap.get(row, "grade_c")),
        "grade_d": _int(cmap.get(row, "grade_d")),
        "grade_f": _int(cmap.get(row, "grade_f")),
        "grade_q": _int(cmap.get(row, "grade_q")),
        "grade_i": _int(cmap.get(row, "grade_i")),
        "grade_s": _int(cmap.get(row, "grade_s")),
        "grade_u": _int(cmap.get(row, "grade_u")),
        "grade_x": _int(cmap.get(row, "grade_x")),
    }
    if gpa is None and not any(v is not None for v in grades.values()):
        return None, "no_values"

    af_total = _int(cmap.get(row, "af_total"))

    enrolled = _int(cmap.get(row, "enrolled"))
    if enrolled is None:
        enrolled = af_total
    if enrolled is None:
        graded = ("grade_a", "grade_b", "grade_c", "grade_d", "grade_f")
        counted = [grades[k] for k in graded if grades.get(k) is not None]
        enrolled = sum(counted) if counted else None

    return (
        ParsedRow(
            dept=dept.strip().upper(),
            number=number.strip().upper(),
            title=cmap.get(row, "title"),
            campus=normalize_campus(cmap.get(row, "campus")),
            college=_label(cmap.get(row, "college")),
            department=_label(cmap.get(row, "department")),
            honors=_bool(cmap.get(row, "honors")),
            term=term_raw,
            term_year=term.year if term else None,
            term_season=term.season if term else None,
            section=cmap.get(row, "section"),
            level=cmap.get(row, "level"),
            source_file=cmap.get(row, "source_file"),
            instructor=instructor.strip(),
            gpa=gpa,
            enrolled=enrolled,
            af_total=af_total,
            grades=grades,
            source_row=index,
        ),
        "",
    )


async def bulk_resolve(
    session: AsyncSession, records: list[ParsedRow]
) -> tuple[dict[str, int], dict[tuple[str, str, bool], int]]:
    """Create every instructor and course up front, then fetch their ids.

    The obvious implementation -- resolve each row as you meet it -- costs one
    round trip per new instructor and per new course. That is 12,000-odd round
    trips for A&M's grade data: half a minute against a local database and
    twenty minutes against a hosted one, which is where this actually runs.
    Batching turns it into about fifty.
    """
    names = {canonical_key(r.instructor): r.instructor for r in records if r.instructor}
    course_keys = {(r.dept, r.number, r.honors): r.title for r in records}

    instructor_rows = [
        {
            "full_name": name,
            "normalized_name": normalize_name(name),
            "canonical_key": key,
        }
        for key, name in names.items()
    ]
    insert_instructors = pg_insert(instructors).on_conflict_do_update(
        index_elements=[instructors.c.canonical_key],
        # Nothing to change on conflict, but ON CONFLICT DO UPDATE is what makes
        # the row visible to the id lookup below in the same transaction.
        set_={"full_name": instructors.c.full_name},
    )
    for start in range(0, len(instructor_rows), BATCH_SIZE):
        await session.execute(insert_instructors, instructor_rows[start : start + BATCH_SIZE])

    course_rows = [
        {"dept": dept, "number": number, "honors": honors, "title": title}
        for (dept, number, honors), title in course_keys.items()
    ]
    insert_courses = pg_insert(courses).on_conflict_do_update(
        constraint="courses_identity",
        set_={"title": func.coalesce(courses.c.title, pg_insert(courses).excluded.title)},
    )
    for start in range(0, len(course_rows), BATCH_SIZE):
        await session.execute(insert_courses, course_rows[start : start + BATCH_SIZE])

    await session.commit()

    instructor_ids = {
        str(row[1]): int(row[0])
        for row in (
            await session.execute(
                text(
                    "select id, canonical_key from instructors "
                    "where canonical_key = any(cast(:keys as text[]))"
                ),
                {"keys": list(names)},
            )
        ).all()
    }
    course_ids = {
        (str(row[1]), str(row[2]), bool(row[3])): int(row[0])
        for row in (
            await session.execute(
                text("select id, upper(dept), upper(number), honors from courses")
            )
        ).all()
    }
    return instructor_ids, course_ids


class Resolver:
    """Instructor and course ids, created on first sight and then remembered.

    Kept for small files and for --limit runs; load() uses bulk_resolve, which
    is the same thing in two statements rather than two thousand.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._instructors: dict[str, int] = {}
        self._courses: dict[tuple[str, str, bool], int] = {}

    async def instructor_id(self, name: str) -> int:
        key = canonical_key(name)
        if key in self._instructors:
            return self._instructors[key]
        stmt = (
            pg_insert(instructors)
            .values(
                full_name=name,
                normalized_name=normalize_name(name),
                canonical_key=key,
            )
            .on_conflict_do_update(
                index_elements=[instructors.c.canonical_key],
                set_={"full_name": instructors.c.full_name},
            )
            .returning(instructors.c.id)
        )
        instructor_id = int((await self._session.execute(stmt)).scalar_one())
        self._instructors[key] = instructor_id
        return instructor_id

    async def course_id(self, dept: str, number: str, title: str | None, honors: bool) -> int:
        key = (dept, number, honors)
        if key in self._courses:
            return self._courses[key]
        stmt = (
            pg_insert(courses)
            .values(dept=dept, number=number, title=title, honors=honors)
            .on_conflict_do_update(
                constraint="courses_identity",
                set_={"title": func.coalesce(courses.c.title, title)},
            )
            .returning(courses.c.id)
        )
        course_id = int((await self._session.execute(stmt)).scalar_one())
        self._courses[key] = course_id
        return course_id

    @property
    def counts(self) -> tuple[int, int]:
        return len(self._instructors), len(self._courses)


_grade_insert = pg_insert(course_grades)
_GRADE_UPDATABLE = (
    "gpa",
    "enrolled",
    "af_total",
    "campus",
    "level",
    "college",
    "department",
    "source_file",
    "grade_i",
    "grade_s",
    "grade_u",
    "grade_x",
    "grade_a",
    "grade_b",
    "grade_c",
    "grade_d",
    "grade_f",
    "grade_q",
    "term_year",
    "term_season",
)
#: Re-running the same file refreshes the numbers instead of duplicating rows.
_GRADE_UPSERT = _grade_insert.on_conflict_do_update(
    constraint="course_grades_identity",
    set_={name: _grade_insert.excluded[name] for name in _GRADE_UPDATABLE},
)


def read_rows(path: Path, delimiter: str | None) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        if delimiter is None:
            head = handle.read(8192)
            handle.seek(0)
            try:
                delimiter = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = [h for h in (reader.fieldnames or []) if h is not None]
        return headers, list(reader)


async def load(
    path: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    delimiter: str | None = None,
) -> Stats:
    headers, rows = read_rows(path, delimiter)
    cmap = resolve_columns(headers)
    if cmap.missing_required:
        raise SystemExit(
            "cannot load: unmapped required fields "
            + ", ".join(cmap.missing_required)
            + "\nrun `python -m app.ingest.profile_csv <file>` and set OVERRIDES "
            "in app/ingest/columns.py"
        )
    log.info("mapped %d fields: %s", len(cmap.fields), ", ".join(sorted(cmap.fields)))

    stats = Stats()
    parsed: list[ParsedRow] = []
    for index, row in enumerate(rows, start=1):
        if limit is not None and stats.rows_read >= limit:
            break
        stats.rows_read += 1
        record, reason = parse_row(row, cmap, index)
        if record is None:
            stats.skip(reason)
            continue
        parsed.append(record)

    if dry_run:
        stats.instructors_seen = len({canonical_key(r.instructor) for r in parsed})
        stats.courses_seen = len({(r.dept, r.number, r.honors) for r in parsed})
        stats.rows_loaded = 0
        for record in parsed[:3]:
            log.info("sample %s", record)
        log.info("DRY RUN %s (nothing written)", stats.report())
        return stats

    async with session_scope() as session:
        instructor_ids, course_ids = await bulk_resolve(session, parsed)
        stats.instructors_seen = len(instructor_ids)
        stats.courses_seen = len(course_ids)
        batch: list[dict[str, Any]] = []
        for record in parsed:
            course_id = course_ids.get((record.dept, record.number, record.honors))
            if course_id is None:
                stats.skip("unresolved_course")
                continue
            batch.append(
                {
                    "instructor_id": instructor_ids.get(canonical_key(record.instructor)),
                    "course_id": course_id,
                    "term": record.term,
                    "term_year": record.term_year,
                    "term_season": record.term_season,
                    "section": record.section,
                    "campus": record.campus,
                    "college": record.college,
                    "department": record.department,
                    "level": record.level,
                    "source_file": record.source_file,
                    "gpa": record.gpa,
                    "enrolled": record.enrolled,
                    "af_total": record.af_total,
                    "source_row": record.source_row,
                    **record.grades,
                }
            )
            if len(batch) >= BATCH_SIZE:
                await session.execute(_GRADE_UPSERT, batch)
                stats.rows_loaded += len(batch)
                await session.commit()
                log.info("loaded %d rows", stats.rows_loaded)
                batch = []
        if batch:
            await session.execute(_GRADE_UPSERT, batch)
            stats.rows_loaded += len(batch)
            await session.commit()
        version = await bump_data_version(session)
        log.info("data_version now %d (hot cache invalidated)", version)

    log.info("done %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delimiter", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(load(args.path, dry_run=args.dry_run, limit=args.limit, delimiter=args.delimiter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
