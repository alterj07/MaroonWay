"""Load a term's sections -- the meeting times the scheduler needs.

    python -m app.ingest.load_sections sections.csv --dry-run
    python -m app.ingest.load_sections sections.csv

A&M shut down its public course API in 2023, so there is no scrape to run: the
replacement needs a student login. This loader therefore takes whatever export
you can get, mapped through app/ingest/columns.py like every other file. It
wants, per row: term, subject, number, section, instructor, days, start time,
end time, and optionally building, room, campus, delivery, honors, seats.

One section with two meeting patterns (a lecture plus a lab) is two rows; they
are grouped onto one section, because it is one thing you register for.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ingest.columns import ColumnMap, resolve_columns, split_course_code
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.ingest.load_grades import normalize_campus, read_rows
from app.models import sections
from app.services.names import canonical_key
from app.services.scheduling import format_time, parse_days, parse_time
from app.services.terms import parse_term

log = logging.getLogger("ingest.sections")

BATCH_SIZE = 500
DELIVERY = {
    "web": "WEB", "online": "WEB", "remote": "WEB",
    "f2f": "F2F", "face to face": "F2F", "in person": "F2F", "lecture": "F2F",
    "hybrid": "HYBRID", "mixed": "HYBRID",
}

_insert = pg_insert(sections)
_UPSERT = _insert.on_conflict_do_update(
    constraint="sections_identity",
    set_={
        name: getattr(_insert.excluded, name)
        for name in ("instructor_id", "campus", "delivery", "honors", "meets", "seats", "seats_open")
    },
)


@dataclass(slots=True)
class Stats:
    rows_read: int = 0
    sections_loaded: int = 0
    meetings: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    unknown_courses: set[str] = field(default_factory=set)
    unknown_instructors: set[str] = field(default_factory=set)

    def skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def report(self) -> str:
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(self.skip_reasons.items()))
        return (
            f"read={self.rows_read} sections={self.sections_loaded}"
            f" meetings={self.meetings} skipped={self.rows_skipped}"
            + (f" [{reasons}]" if reasons else "")
        )


def normalize_delivery(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().lower()
    for needle, code in DELIVERY.items():
        if needle in lowered:
            return code
    return None


def _bool(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in {"1", "y", "yes", "t", "true", "h", "honors"}


def _int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value.replace(",", "").strip()))
    except ValueError:
        return None


@dataclass(slots=True)
class ParsedRow:
    term: str
    dept: str
    number: str
    section_code: str
    instructor: str | None
    campus: str | None
    delivery: str | None
    honors: bool
    seats: int | None
    seats_open: int | None
    meetings: list[dict[str, Any]]


def parse_row(row: dict[str, str], cmap: ColumnMap) -> tuple[ParsedRow | None, str]:
    dept = cmap.get(row, "dept")
    number = cmap.get(row, "number")
    if not (dept and number):
        split = split_course_code(cmap.get(row, "course_code"))
        if split is None:
            return None, "no_course_code"
        dept, number = split

    term = cmap.get(row, "term")
    if not term:
        return None, "no_term"
    section_code = cmap.get(row, "section")
    if not section_code:
        return None, "no_section"

    days = parse_days(cmap.get(row, "days"))
    start = parse_time(cmap.get(row, "start_time"))
    end = parse_time(cmap.get(row, "end_time"))
    delivery = normalize_delivery(cmap.get(row, "delivery"))

    meetings: list[dict[str, Any]] = []
    if days and start is not None and end is not None and end > start:
        for day in days:
            meetings.append(
                {
                    "day": day,
                    "start": format_time(start),
                    "end": format_time(end),
                    "building": cmap.get(row, "building"),
                    "room": cmap.get(row, "room"),
                }
            )
    elif delivery != "WEB":
        # No usable time and not flagged online: keep the section, but it cannot
        # be scheduled against, so say so rather than inventing a time.
        return (
            ParsedRow(
                term=term, dept=dept.upper(), number=number.upper(),
                section_code=section_code, instructor=cmap.get(row, "instructor"),
                campus=normalize_campus(cmap.get(row, "campus")), delivery=delivery,
                honors=_bool(cmap.get(row, "honors")), seats=_int(cmap.get(row, "seats")),
                seats_open=None, meetings=[],
            ),
            "no_meeting_time",
        )

    return (
        ParsedRow(
            term=term,
            dept=dept.upper(),
            number=number.upper(),
            section_code=section_code,
            instructor=cmap.get(row, "instructor"),
            campus=normalize_campus(cmap.get(row, "campus")),
            delivery=delivery or ("WEB" if not meetings else "F2F"),
            honors=_bool(cmap.get(row, "honors")),
            seats=_int(cmap.get(row, "seats")),
            seats_open=_int(cmap.get(row, "seats_open")),
            meetings=meetings,
        ),
        "",
    )


async def load(path: Path, *, dry_run: bool = False, limit: int | None = None) -> Stats:
    headers, rows = read_rows(path, None)
    cmap = resolve_columns(headers)
    required = [f for f in ("term", "section") if f not in cmap.fields]
    if required or not ({"dept", "number"} <= set(cmap.fields) or "course_code" in cmap.fields):
        raise SystemExit(
            "cannot load sections: missing " + ", ".join(required or ["dept/number"]) + "\n"
            "run `python -m app.ingest.profile_csv <file>` and set OVERRIDES in "
            "app/ingest/columns.py"
        )
    log.info("mapped %d fields: %s", len(cmap.fields), ", ".join(sorted(cmap.fields)))
    if not cmap.schedule_fields:
        log.warning(
            "this file carries none of %s -- sections will load with no meeting "
            "times, and the scheduler cannot use them",
            ", ".join(("days", "start_time", "end_time")),
        )

    stats = Stats()
    # One section can have several meeting rows; group them.
    grouped: dict[tuple[str, str, str, str], ParsedRow] = {}
    for row in rows:
        if limit is not None and stats.rows_read >= limit:
            break
        stats.rows_read += 1
        record, reason = parse_row(row, cmap)
        if record is None:
            stats.skip(reason)
            continue
        if reason:
            stats.skip(reason)
        key = (record.term, record.dept, record.number, record.section_code)
        if key in grouped:
            grouped[key].meetings.extend(record.meetings)
        else:
            grouped[key] = record

    log.info("%d distinct sections across %d rows", len(grouped), stats.rows_read)
    if dry_run:
        for record in list(grouped.values())[:3]:
            log.info(
                "sample %s %s-%s %s %s",
                record.term, record.dept, record.number, record.section_code,
                [m["day"] + " " + m["start"] + "-" + m["end"] for m in record.meetings],
            )
        log.info("DRY RUN %s (nothing written)", stats.report())
        return stats

    async with session_scope() as session:
        courses = {
            (row[1], row[2]): int(row[0])
            for row in (
                await session.execute(text("select id, upper(dept), upper(number) from courses"))
            ).all()
        }
        instructors = {
            str(row[1]): int(row[0])
            for row in (await session.execute(text("select id, canonical_key from instructors"))).all()
        }

        payload: list[dict[str, Any]] = []
        for record in grouped.values():
            course_id = courses.get((record.dept, record.number))
            if course_id is None:
                stats.unknown_courses.add(f"{record.dept} {record.number}")
                stats.skip("unknown_course")
                continue
            instructor_id = None
            if record.instructor:
                instructor_id = instructors.get(canonical_key(record.instructor))
                if instructor_id is None:
                    stats.unknown_instructors.add(record.instructor)
            term = parse_term(record.term)
            payload.append(
                {
                    "course_id": course_id,
                    "instructor_id": instructor_id,
                    "term": record.term,
                    "section_code": record.section_code,
                    "campus": record.campus,
                    "delivery": record.delivery,
                    "honors": record.honors,
                    "meets": record.meetings,
                    "seats": record.seats,
                    "seats_open": record.seats_open,
                }
            )
            stats.meetings += len(record.meetings)
            if term is None:
                stats.skip("unparsed_term")

        for start in range(0, len(payload), BATCH_SIZE):
            batch = payload[start : start + BATCH_SIZE]
            await session.execute(_UPSERT, batch)
            stats.sections_loaded += len(batch)
        await session.commit()
        version = await bump_data_version(session)
        log.info("data_version now %d (hot cache invalidated)", version)

    if stats.unknown_courses:
        log.warning(
            "%d course codes are not in the catalog, e.g. %s",
            len(stats.unknown_courses),
            ", ".join(sorted(stats.unknown_courses)[:5]),
        )
    if stats.unknown_instructors:
        log.warning(
            "%d instructors had no matching row, e.g. %s",
            len(stats.unknown_instructors),
            ", ".join(sorted(stats.unknown_instructors)[:5]),
        )
    log.info("done %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(load(args.path, dry_run=args.dry_run, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
