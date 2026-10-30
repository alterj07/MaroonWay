"""Load a term from A&M's public class schedule.

    python -m app.ingest.load_public_schedule --term 202631 --dry-run
    python -m app.ingest.load_public_schedule --term 202631
    python -m app.ingest.load_public_schedule --list-terms

Texas A&M publishes its whole class schedule with no login, because TEC 51.974
requires it. That replaces everything this project used to do to get class
times: no userscript, no browser, no scraping a page behind Duo, and no
vendor's authenticated API. Two requests give a term.

    GET  /api/all-terms        every term, as Banner's own STVTERM rows
    POST /api/course-sections  {"termCode": "202631"} -- the whole term at once

Measured against Fall 2026: 14,350 sections, 99.8% carrying an instructor and
100% carrying meetings.

Two fields do the work. ``SWV_CLASS_SEARCH_INSTRCTR_JSON`` gives each
instructor's full name *and a stable A&M person id*, which is what finally
tells ten different people called "KIM J" apart -- among 4,429 College Station
instructors there are 208 collisions on surname plus initial but only 3 on the
full name. ``SWV_CLASS_SEARCH_JSON_CLOB`` gives the meetings, with a type on
each, so a November exam sitting can be kept out of a weekly timetable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

import httpx

from app.ingest.common import configure_logging
from app.ingest.load_sections import ParsedRow, Stats, persist

log = logging.getLogger("ingest.public_schedule")

BASE = "https://howdyportal.tamu.edu/api"

#: Meetings a student attends every week. An "Examination" is one sitting on
#: one date in November: it has the shape of a weekly meeting and would import
#: as a recurring block, putting a phantom class on the calendar and wrecking
#: every gap calculation. Fall 2026 carries 837 of them.
WEEKLY = frozenset(
    {"Lecture", "Laboratory", "Seminar", "Recitation", "Practicum", "Studio", "Field Work"}
)

_DAY_FIELDS = (
    ("SSRMEET_MON_DAY", "MON"),
    ("SSRMEET_TUE_DAY", "TUE"),
    ("SSRMEET_WED_DAY", "WED"),
    ("SSRMEET_THU_DAY", "THU"),
    ("SSRMEET_FRI_DAY", "FRI"),
    ("SSRMEET_SAT_DAY", "SAT"),
    ("SSRMEET_SUN_DAY", "SUN"),
)

_SEASONS = {"spring": "SPRING", "summer": "SUMMER", "fall": "FALL", "winter": "WINTER"}
_CAMPUSES = {
    "college station": "CSTAT",
    "galveston": "GALV",
    "qatar": "QATAR",
    "blinn": "BLINN",
}


def parse_term_desc(desc: str) -> tuple[str | None, str | None]:
    """``Fall 2026 - College Station`` -> ``("FALL 2026", "CSTAT")``.

    The same convention load_complete_term.py uses, so both loaders write terms
    the scheduler can compare.
    """
    head, _, tail = str(desc or "").partition(" - ")
    parts = head.strip().split()
    if len(parts) != 2:
        return None, None
    season = _SEASONS.get(parts[0].lower())
    if not season or not parts[1].isdigit():
        return None, None
    return f"{season} {parts[1]}", _CAMPUSES.get(tail.strip().lower())


def clock(value: Any) -> str | None:
    """``"01:50 PM"`` -> ``"13:50"``. Returns None for anything unreadable."""
    text = str(value or "").strip().upper()
    if not text:
        return None
    body, _, suffix = text.partition(" ")
    hours, _, minutes = body.partition(":")
    if not (hours.isdigit() and minutes.isdigit()):
        return None
    hour, minute = int(hours), int(minutes)
    if suffix == "PM" and hour < 12:
        hour += 12
    elif suffix == "AM" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def meetings_of(raw: Any) -> list[dict[str, Any]]:
    """Weekly meetings only, one row per day."""
    try:
        blocks = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if (block.get("SSRMEET_MTYP_CODE") or "") not in WEEKLY:
            continue
        start, end = clock(block.get("SSRMEET_BEGIN_TIME")), clock(block.get("SSRMEET_END_TIME"))
        if not (start and end):
            continue
        for field, day in _DAY_FIELDS:
            if block.get(field):
                out.append(
                    {
                        "day": day,
                        "start": start,
                        "end": end,
                        "building": block.get("SSRMEET_BLDG_CODE") or None,
                        "room": block.get("SSRMEET_ROOM_CODE") or None,
                    }
                )
    return out


def instructor_of(raw: Any) -> tuple[str | None, int | None]:
    """The instructor of record and their A&M id.

    A&M marks the primary with "(P)". Where several are listed the primary is
    the one taught under; our schema holds one, and joining the names would
    invent a person who does not exist.
    """
    try:
        people = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return None, None
    if not isinstance(people, list) or not people:
        return None, None
    chosen = next((p for p in people if "(P)" in str(p.get("NAME", ""))), people[0])
    name = str(chosen.get("NAME") or "").replace("(P)", "").replace("(S)", "").strip()
    person = chosen.get("MORE")
    return (name or None), (int(person) if isinstance(person, int) else None)


def delivery_of(row: dict[str, Any], meetings: list[dict[str, Any]]) -> str | None:
    """WEB, F2F, or nothing when the feed does not say.

    Null is a real answer: reading a blank as online is how a class a student
    has to walk to ends up excluded from the campus-travel checks.
    """
    site = str(row.get("SWV_CLASS_SEARCH_SITE") or "").strip().lower()
    kind = str(row.get("SWV_CLASS_SEARCH_INST_TYPE") or "").strip().lower()
    if "online" in site or "distance" in site or "online" in kind or "web" in kind:
        return "WEB"
    if site or meetings:
        return "F2F"
    return None


def to_record(row: dict[str, Any], term: str, campus: str | None) -> ParsedRow | None:
    dept = str(row.get("SWV_CLASS_SEARCH_SUBJECT") or "").strip().upper()
    number = str(row.get("SWV_CLASS_SEARCH_COURSE") or "").strip().upper()
    section = str(row.get("SWV_CLASS_SEARCH_SECTION") or "").strip()
    if not (dept and number and section):
        return None

    meetings = meetings_of(row.get("SWV_CLASS_SEARCH_JSON_CLOB"))
    name, person_id = instructor_of(row.get("SWV_CLASS_SEARCH_INSTRCTR_JSON"))
    site = str(row.get("SWV_CLASS_SEARCH_SITE") or "").strip().lower()

    def seats(key: str) -> int | None:
        value = str(row.get(key) or "").strip()
        return int(value) if value.isdigit() else None

    return ParsedRow(
        term=term,
        dept=dept,
        number=number,
        section_code=section,
        instructor=name,
        # The section's own site wins; the term's campus is the fallback, since
        # a College Station term still lists a few sections taught elsewhere.
        campus=_CAMPUSES.get(site) or campus,
        delivery=delivery_of(row, meetings),
        honors="HONORS" in str(row.get("SWV_CLASS_SEARCH_ATTRIBUTES") or "").upper(),
        seats=seats("SWV_CLASS_SEARCH_MAX_ENRL"),
        seats_open=seats("SWV_CLASS_SEARCH_SEATS_AVAIL"),
        meetings=meetings,
        person_id=person_id,
    )


async def fetch_terms(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(f"{BASE}/all-terms")
    response.raise_for_status()
    return response.json()


async def fetch_sections(client: httpx.AsyncClient, term_code: str) -> list[dict[str, Any]]:
    response = await client.post(f"{BASE}/course-sections", json={"termCode": term_code})
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise RuntimeError(f"expected a list of sections, got {type(rows).__name__}")
    return rows


async def run(term_code: str, *, dry_run: bool, limit: int | None) -> Stats:
    # Generous: a term is ~24MB and the server takes a while to assemble it.
    async with httpx.AsyncClient(timeout=180.0) as client:
        terms = await fetch_terms(client)
        match = next((t for t in terms if str(t.get("STVTERM_CODE")) == term_code), None)
        if match is None:
            raise SystemExit(f"no term {term_code}; run --list-terms")
        term, campus = parse_term_desc(match.get("STVTERM_DESC", ""))
        if term is None:
            raise SystemExit(f"cannot read a term out of {match.get('STVTERM_DESC')!r}")
        log.info("%s -> %s (%s)", match["STVTERM_DESC"], term, campus or "campus unknown")

        rows = await fetch_sections(client, term_code)
    log.info("%d sections", len(rows))

    records: list[ParsedRow] = []
    no_course = no_instructor = no_meetings = 0
    for row in rows[: limit or len(rows)]:
        record = to_record(row, term, campus)
        if record is None:
            no_course += 1
            continue
        if record.person_id is None:
            no_instructor += 1
        if not record.meetings:
            no_meetings += 1
        records.append(record)

    log.info(
        "%d usable; %d without a course code, %d without an identified instructor, "
        "%d without weekly meetings",
        len(records), no_course, no_instructor, no_meetings,
    )
    if dry_run:
        for record in records[:5]:
            log.info("  %s %s-%s %s %s", record.dept, record.number, record.section_code,
                     record.instructor, record.meetings[:1])
        log.info("dry run: nothing written")
        return Stats()
    return await persist(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", help="STVTERM_CODE, e.g. 202631")
    parser.add_argument("--list-terms", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    if args.list_terms:
        async def show() -> None:
            async with httpx.AsyncClient(timeout=60.0) as client:
                for t in await fetch_terms(client):
                    term, campus = parse_term_desc(t.get("STVTERM_DESC", ""))
                    if term:
                        print(f"{t['STVTERM_CODE']}  {t['STVTERM_DESC']}  -> {term} {campus or ''}")
        asyncio.run(show())
        return 0

    if not args.term:
        parser.error("--term is required (or --list-terms)")
    stats = asyncio.run(run(args.term, dry_run=args.dry_run, limit=args.limit))
    log.info("done %s", stats.report() if hasattr(stats, "report") else stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
