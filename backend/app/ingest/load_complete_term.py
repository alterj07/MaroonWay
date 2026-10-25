"""Load a term from the complete export -- sections, professors and ratings.

    python -m app.ingest.load_complete_term ../Data/output/spring_2027_complete.csv --dry-run
    python -m app.ingest.load_complete_term ../Data/output/spring_2027_complete.csv

This file is a different animal from the other inputs. Every other loader takes
one slice -- grades here, a RateMyProfessors scrape there, meeting times from a
Banner cache -- and leaves this project to join them on instructor names, which
is where it has always lost people. This export arrives already joined: each
section carries its instructors, and each instructor carries the RMP id that was
matched to them, the rating behind it, and the grade history under their name.

So the hardest, least reliable step in the pipeline is simply skipped for every
row that arrives matched. What cannot be matched says so in
``rmp_match_status`` rather than being guessed at.

Three columns decide what a section is:

``meeting_time_status``
    ``complete`` or ``partial`` means real times. ``no_fixed_times`` means the
    section has none, and it is loaded with no meetings so the scheduler leaves
    it out of a verified schedule rather than quietly placing it.

``instruction_type``
    Only ``Web Based`` and ``Synchronous Video/Web Conf`` are online. Half this
    file is ``Non-traditional``, ``Internship`` or ``Study Abroad``: those have
    no fixed times either, but they are not online classes, and calling them one
    is the mistake that let a Galveston class and a College Station class sit in
    the same "conflict-free" week.

``term_name``
    ``Spring 2027 - College Station`` carries the campus, since the campus
    column alone also holds teaching sites (McAllen, Fort Worth) that are not
    campuses this schema knows.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.ingest.load_sections import ParsedRow, persist
from app.services.names import canonical_key, normalize_name

log = logging.getLogger("ingest.complete")

#: The export's day names, in the scheduler's vocabulary.
_DAYS = {
    "mon": "MON",
    "tue": "TUE",
    "wed": "WED",
    "thu": "THU",
    "fri": "FRI",
    "sat": "SAT",
    "sun": "SUN",
}

#: Only these two are actually online. Everything else without fixed times is a
#: class whose times we do not know, which is a different thing entirely.
_ONLINE_TYPES = {"web based", "synchronous video/web conf"}

#: Teaching sites the schema has a code for. McAllen, Fort Worth and the
#: dentistry campus are real places this column cannot express, so they are left
#: null rather than being forced into the nearest code.
_CAMPUSES = {"college station": "CSTAT", "galveston": "GALV", "blinn": "BLINN"}

_SEASONS = {"spring": "SPRING", "summer": "SUMMER", "fall": "FALL", "winter": "WINTER"}


def parse_term(term_name: str) -> tuple[str | None, str | None]:
    """``Spring 2027 - College Station`` -> ``("SPRING 2027", "CSTAT")``."""
    head, _, tail = term_name.partition(" - ")
    parts = head.strip().split()
    if len(parts) != 2:
        return None, None
    season = _SEASONS.get(parts[0].strip().lower())
    year = parts[1].strip()
    if not season or not year.isdigit():
        return None, None
    return f"{season} {year}", _CAMPUSES.get(tail.strip().lower())


def parse_meetings(raw: str, status: str) -> list[dict[str, Any]]:
    """Meetings with real times, or nothing at all.

    A row with no fixed times still lists its days, which is how a class with
    nowhere to be ends up drawn at nine in the morning. Without a start and an
    end there is nothing to place, so it is not placed.
    """
    if status == "no_fixed_times":
        return []
    try:
        blocks = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []

    out: list[dict[str, Any]] = []
    for block in blocks:
        start, end = block.get("start_time"), block.get("end_time")
        if not (start and end):
            continue
        for day in block.get("days") or []:
            name = _DAYS.get(str(day).strip().lower())
            if not name:
                continue
            out.append(
                {
                    "day": name,
                    "start": start,
                    "end": end,
                    "building": (block.get("building") or None),
                    "room": (block.get("room") or None),
                }
            )
    return out


def delivery_of(instruction_type: str, meetings: list[dict[str, Any]]) -> str | None:
    """``F2F`` or ``WEB`` -- or nothing, when it is not known.

    Null is a real answer here. The alternative, reading a blank as online, is
    what issue #6 was about.
    """
    kind = (instruction_type or "").strip().lower()
    if kind in _ONLINE_TYPES:
        # WEB whether or not it has meeting times. A synchronous online class
        # meets at its times and the scheduler still checks them, but it is not
        # on a campus -- HYBRID would reinstate the cross-campus check that
        # `is_online` exists to skip.
        return "WEB"
    if kind == "traditional face-to-face (f2f)":
        return "F2F"
    return None


def primary_instructor(raw: str) -> tuple[str | None, dict[str, Any] | None]:
    """The instructor of record, and their matched RMP details."""
    try:
        people = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return None, None
    if not people:
        return None, None
    chosen = next((p for p in people if p.get("primary")), people[0])
    name = (chosen.get("name") or "").strip()
    return (name or None), chosen


def read_rows(path: Path) -> tuple[list[ParsedRow], dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, int]]:
    """Parse the export once, into what each table needs.

    Returns the sections, the instructors keyed by canonical name, the course
    detail keyed by (dept, number), and a tally of what was skipped and why.
    """
    csv.field_size_limit(50_000_000)
    sections: list[ParsedRow] = []
    people: dict[str, dict[str, Any]] = {}
    courses: dict[tuple[str, str], dict[str, Any]] = {}
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            term, campus = parse_term(row.get("term_name") or "")
            if not term:
                skip("no_term")
                continue
            dept = (row.get("subject") or "").strip().upper()
            number = (row.get("course_number") or "").strip().upper()
            section_code = (row.get("section") or "").strip()
            if not (dept and number and section_code):
                skip("no_course_code")
                continue

            meetings = parse_meetings(
                row.get("meetings_json") or "", (row.get("meeting_time_status") or "").strip()
            )
            name, details = primary_instructor(row.get("professor_details_json") or "")
            honors = (row.get("is_honors") or "").strip().lower() == "true"

            sections.append(
                ParsedRow(
                    term=term,
                    dept=dept,
                    number=number,
                    section_code=section_code,
                    instructor=name,
                    # The section's own site, where it is one this schema knows.
                    campus=_CAMPUSES.get((row.get("campus") or "").strip().lower()) or campus,
                    delivery=delivery_of(row.get("instruction_type") or "", meetings),
                    honors=honors,
                    seats=None,
                    seats_open=_int(row.get("open_seats")),
                    meetings=meetings,
                )
            )

            if name and details:
                key = canonical_key(name)
                known = people.get(key)
                # One row per person: later rows only fill gaps, so a section
                # whose match failed cannot erase a match made elsewhere.
                if known is None or (known.get("rmp_id") is None and details.get("rmp_professor_id")):
                    people[key] = {
                        "full_name": name,
                        "normalized_name": normalize_name(name),
                        "canonical_key": key,
                        "rmp_id": _int(details.get("rmp_professor_id")),
                        "rating": _float(details.get("rmp_rating")),
                        "difficulty": _float(details.get("rmp_difficulty")),
                        "reviews": _int(details.get("rmp_review_count")) or 0,
                        "would_take_again": _float(details.get("rmp_would_take_again_pct")),
                        "match_status": details.get("rmp_match_status"),
                    }

            detail = courses.setdefault((dept, number), {})
            for column, value in (
                ("title", (row.get("course_title") or "").strip()),
                ("credits", (row.get("credit_hours") or "").strip()),
                ("prereq_text", (row.get("prerequisite_text") or "").strip()),
                ("coreq_text", (row.get("corequisite_text") or "").strip()),
            ):
                if value and not detail.get(column):
                    detail[column] = value

    return sections, people, courses, skipped


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


async def ensure_people(people: dict[str, dict[str, Any]]) -> int:
    """Create the instructors this export knows that the database does not.

    ``persist`` resolves a section's instructor by name and leaves it null when
    the name is new, so without this step a term's new hires teach nothing. It
    runs first for that reason: once the row exists, ``persist`` finds it and
    the section is attached rather than orphaned.
    """
    if not people:
        return 0
    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                insert into instructors (full_name, normalized_name, canonical_key)
                values (:full_name, :normalized_name, :canonical_key)
                on conflict (canonical_key) do nothing
                """
            ),
            [
                {
                    "full_name": p["full_name"],
                    "normalized_name": p["normalized_name"],
                    "canonical_key": p["canonical_key"],
                }
                for p in people.values()
            ],
        )
        await session.commit()
    return result.rowcount or 0


async def write_people(people: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Attach matched RMP ids and their ratings to the instructors.

    ``persist`` has already created every instructor by name. This adds what the
    export knew about them, which is the part this project used to have to guess.
    """
    matched = [p for p in people.values() if p["rmp_id"]]
    counts = {"people": len(people), "matched": len(matched), "rated": 0}
    if not matched:
        return counts

    async with session_scope() as session:
        # The ratings first: instructors.rmp_id points at this table.
        rated = [p for p in matched if p["rating"] is not None]
        if rated:
            await session.execute(
                text(
                    """
                    insert into rmp_professors (
                        rmp_id, full_name, avg_rating, avg_difficulty,
                        num_ratings, would_take_again_percent
                    )
                    values (
                        :rmp_id, :full_name, :rating, :difficulty,
                        :reviews, :would_take_again
                    )
                    on conflict (rmp_id) do update set
                        full_name                = excluded.full_name,
                        avg_rating               = excluded.avg_rating,
                        avg_difficulty           = excluded.avg_difficulty,
                        num_ratings              = excluded.num_ratings,
                        would_take_again_percent = excluded.would_take_again_percent,
                        fetched_at               = now()
                    """
                ),
                rated,
            )
            counts["rated"] = len(rated)

        # Then the link. Two people can carry the same id only if the export
        # matched them both to it; the unique index would reject the second, so
        # the id is only set where nothing else already holds it.
        await session.execute(
            text(
                """
                update instructors as i
                   set rmp_id = v.rmp_id
                  from (values (:canonical_key, cast(:rmp_id as bigint))) as v (canonical_key, rmp_id)
                 where i.canonical_key = v.canonical_key
                   and i.rmp_id is distinct from v.rmp_id
                   and not exists (
                       select 1 from instructors other
                        where other.rmp_id = v.rmp_id and other.id <> i.id
                   )
                """
            ),
            [{"canonical_key": p["canonical_key"], "rmp_id": p["rmp_id"]} for p in matched],
        )
        await session.commit()
    return counts


async def write_courses(courses: dict[tuple[str, str], dict[str, Any]]) -> int:
    """Fill in each course's title, credits and prerequisites."""
    payload = [
        {
            "dept": dept,
            "number": number,
            "title": detail.get("title"),
            "credits": detail.get("credits"),
            "prereq_text": detail.get("prereq_text"),
            "coreq_text": detail.get("coreq_text"),
        }
        for (dept, number), detail in courses.items()
        if any(detail.get(k) for k in ("title", "credits", "prereq_text", "coreq_text"))
    ]
    if not payload:
        return 0
    async with session_scope() as session:
        # Only fills blanks: a title loaded from the catalog is not replaced by
        # the schedule's abbreviated one.
        await session.execute(
            text(
                """
                update courses as c
                   set title       = coalesce(c.title, v.title),
                       credits     = coalesce(c.credits, v.credits),
                       prereq_text = coalesce(c.prereq_text, v.prereq_text),
                       coreq_text  = coalesce(c.coreq_text, v.coreq_text)
                  from (values (:dept, :number, :title, :credits, :prereq_text, :coreq_text))
                       as v (dept, number, title, credits, prereq_text, coreq_text)
                 where upper(c.dept) = v.dept and upper(c.number) = v.number
                """
            ),
            payload,
        )
        await session.commit()
    return len(payload)


async def run(path: Path, *, dry_run: bool, limit: int | None) -> int:
    log.info("reading %s", path)
    sections, people, courses, skipped = read_rows(path)
    if limit:
        sections = sections[:limit]

    with_times = sum(1 for s in sections if s.meetings)
    online = sum(1 for s in sections if s.delivery == "WEB")
    unknown = sum(1 for s in sections if s.delivery is None)
    matched = sum(1 for p in people.values() if p["rmp_id"])

    log.info(
        "%d sections (%d with times, %d online, %d delivery unknown)",
        len(sections),
        with_times,
        online,
        unknown,
    )
    log.info("%d instructors, %d matched to RateMyProfessors", len(people), matched)
    log.info("%d courses with catalog detail", len(courses))
    if skipped:
        log.info("skipped: %s", skipped)

    if dry_run:
        log.info("dry run: nothing written")
        return 0

    log.info("instructors created: %d", await ensure_people(people))
    stats = await persist(sections)
    log.info(
        "sections: loaded=%d meetings=%d unresolved instructors=%d",
        stats.sections_loaded,
        stats.meetings,
        len(stats.unknown_instructors),
    )
    log.info("instructors: %s", await write_people(people))
    log.info("courses updated: %d", await write_courses(courses))

    async with session_scope() as session:
        version = await bump_data_version(session)
    log.info("data_version now %d", version)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="the complete term export (CSV)")
    parser.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    parser.add_argument("--limit", type=int, default=None, help="only this many sections")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    if not args.path.exists():
        log.error("no such file: %s", args.path)
        return 2
    return asyncio.run(run(args.path, dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    sys.exit(main())
