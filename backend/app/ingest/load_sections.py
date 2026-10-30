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
from app.services.identity import Name, names_agree, read_name
from app.services.names import canonical_key, normalize_name
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
    #: A&M's own instructor id, where the source carries one. Resolving on it
    #: rather than on a normalised name is what tells ten different people
    #: named "KIM J" apart; sources that only print a name leave it None and
    #: fall back to the name as before.
    person_id: int | None = None


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
            delivery=delivery or ("F2F" if meetings else None),
            honors=_bool(cmap.get(row, "honors")),
            seats=_int(cmap.get(row, "seats")),
            seats_open=_int(cmap.get(row, "seats_open")),
            meetings=meetings,
        ),
        "",
    )


#: Instructors named by the class schedule. The conflict target is the
#: canonical key because that is the table's own unique constraint; where a row
#: already exists under that key and nobody has claimed it, it takes the A&M id
#: rather than a duplicate being made beside it.
_INSTRUCTOR_UPSERT = text(
    """
    insert into instructors (full_name, normalized_name, canonical_key, person_id)
    values (:full_name, :normalized_name, :canonical_key, :person_id)
    on conflict (canonical_key) do update
       set person_id = coalesce(instructors.person_id, excluded.person_id),
           full_name = case
               when instructors.person_id is null then excluded.full_name
               else instructors.full_name
           end
    """
)


async def persist(records: list[ParsedRow], *, stats: Stats | None = None) -> Stats:
    """Write sections, resolving their course and instructor.

    Shared by the CSV loader and by POST /sections/import, so a section
    scraped from a browser goes through exactly the same normalisation,
    resolution and upsert as one from a file.
    """
    stats = stats or Stats()
    async with session_scope() as session:
        courses = {
            (row[1], row[2]): int(row[0])
            for row in (
                await session.execute(text("select id, upper(dept), upper(number) from courses"))
            ).all()
        }
        rows = (
            await session.execute(
                text("select id, canonical_key, person_id, full_name from instructors")
            )
        ).all()
        instructors = {str(row[1]): int(row[0]) for row in rows}
        by_person = {int(row[2]): int(row[0]) for row in rows if row[2] is not None}

        # Attaching A&M's id to the instructors we already hold.
        #
        # This cannot be done by comparing normalised names. The grade reports
        # print "CANTU J" and the class schedule prints "Justin Colt Cantu";
        # those canonicalise differently, so matching on the key adopted almost
        # nobody -- 4,023 instructors ended up with an A&M id and 3,467 with a
        # RateMyProfessors id while only 291 had both, because the row carrying
        # the rating was never the row the scheduler reads.
        #
        # So it goes through the same rule that decides any other identity
        # here: surnames must match, and one given name must be a prefix of the
        # other, which is exactly "J" against "JUSTIN". A grade-report row that
        # fits several of this term's instructors is left alone -- "KIM J" fits
        # ten people, and adopting the first would put one person's ratings on
        # another's classes.
        unclaimed: dict[str, list[tuple[int, Name]]] = {}
        for row in rows:
            if row[2] is not None:
                continue
            parsed = read_name(row[3])
            if parsed is not None:
                unclaimed.setdefault(parsed.surname, []).append((int(row[0]), parsed))

        seen_people: dict[int, str] = {}
        for record in records:
            if record.person_id is not None and record.instructor:
                seen_people.setdefault(record.person_id, record.instructor)

        adopted: list[dict[str, Any]] = []
        contested = 0
        taken: set[int] = set()
        for person_id, name in seen_people.items():
            if person_id in by_person:
                continue
            theirs = read_name(name)
            if theirs is None:
                continue
            fits = [
                (row_id, parsed)
                for row_id, parsed in unclaimed.get(theirs.surname, [])
                if row_id not in taken and names_agree(parsed, theirs)
            ]
            if len(fits) != 1:
                contested += len(fits) > 1
                continue
            row_id = fits[0][0]
            adopted.append({"id": row_id, "person_id": person_id})
            by_person[person_id] = row_id
            taken.add(row_id)

        if adopted:
            await session.execute(
                text("update instructors set person_id = :person_id where id = :id"),
                adopted,
            )
        log.info(
            "attached an A&M id to %d instructors already on record; %d names fit "
            "more than one and were left alone",
            len(adopted), contested,
        )

        # Whoever is left teaches here and we have never heard of them. Creating
        # them is the point: a section whose instructor does not exist loads
        # with nobody attached, and the student is shown a class taught by
        # no one.
        fresh = [
            {
                "full_name": name,
                "normalized_name": normalize_name(name),
                "canonical_key": canonical_key(name),
                "person_id": person_id,
            }
            for person_id, name in seen_people.items()
            if person_id not in by_person
        ]
        if fresh:
            await session.execute(_INSTRUCTOR_UPSERT, fresh)
            refreshed = (
                await session.execute(
                    text("select id, person_id from instructors where person_id is not null")
                )
            ).all()
            by_person = {int(row[1]): int(row[0]) for row in refreshed}
            log.info("created %d instructors this term's schedule names", len(fresh))

        payload: list[dict[str, Any]] = []
        for record in records:
            course_id = courses.get((record.dept, record.number))
            if course_id is None:
                stats.unknown_courses.add(f"{record.dept} {record.number}")
                stats.skip("unknown_course")
                continue
            instructor_id = None
            if record.person_id is not None:
                instructor_id = by_person.get(record.person_id)
            if instructor_id is None and record.instructor:
                instructor_id = instructors.get(canonical_key(record.instructor))
            if instructor_id is None and record.instructor:
                stats.unknown_instructors.add(record.instructor)
            if parse_term(record.term) is None:
                stats.skip("unparsed_term")
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

        for start in range(0, len(payload), BATCH_SIZE):
            batch = payload[start : start + BATCH_SIZE]
            await session.execute(_UPSERT, batch)
            stats.sections_loaded += len(batch)
        await session.commit()
        if stats.sections_loaded:
            version = await bump_data_version(session)
            log.info("data_version now %d (hot cache invalidated)", version)
    return stats


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

    written = await persist(list(grouped.values()), stats=stats)
    stats = written

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
