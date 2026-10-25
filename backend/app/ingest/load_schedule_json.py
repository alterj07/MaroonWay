"""Load A&M's real class schedule from the Compass class-search cache.

    python -m app.ingest.load_schedule_json ../Data/output/schedule_cache/202711.json

Each file is one term's output from the Banner "class search" web service that
Howdy drives -- the ``SWV_CLASS_SEARCH_*`` records. Unlike every other file in
this project it carries **meeting times**: days, start and end, building and
room, which is what the scheduler needed and never had.

Two fields do the work. ``SWV_CLASS_SEARCH_JSON_CLOB`` is a JSON string of
meeting rows, one per pattern, with a column per weekday that holds the day's
letter or null. ``SWV_CLASS_SEARCH_INSTRCTR_JSON`` lists the teaching staff,
the primary one marked "(P)".

Term codes are ``YYYYSC``: season 1 spring, 2 summer, 3 fall, and a trailing
campus digit, 1 College Station and 2 Galveston. The season is confirmed by the
meeting dates in the file -- 202711 runs 01/19/2027 to 05/11/2027.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.ingest.common import configure_logging, session_scope
from app.ingest.load_sections import ParsedRow, Stats, persist
from app.services.names import resolve_name
from app.services.terms import parse_term

log = logging.getLogger("ingest.schedule")

#: SSRMEET column -> the scheduler's day name.
_DAY_COLUMNS = {
    "SSRMEET_MON_DAY": "MON",
    "SSRMEET_TUE_DAY": "TUE",
    "SSRMEET_WED_DAY": "WED",
    "SSRMEET_THU_DAY": "THU",
    "SSRMEET_FRI_DAY": "FRI",
    "SSRMEET_SAT_DAY": "SAT",
    "SSRMEET_SUN_DAY": "SUN",
}

#: Trailing digit of the term code.
_CAMPUS_BY_CODE = {"1": "CSTAT", "2": "GALV"}

_SEASON_NAMES = {"spring": "SPRING", "summer": "SUMMER", "fall": "FALL"}


def term_name(code: str) -> str | None:
    """"202711" -> "SPRING 2027"; the readable form the rest of the app uses."""
    parsed = parse_term(code)
    if parsed is None:
        return None
    return f"{_SEASON_NAMES[parsed.season]} {parsed.year}"


def campus_of(code: str) -> str | None:
    return _CAMPUS_BY_CODE.get(code[-1]) if code else None


def parse_clock(value: str | None) -> str | None:
    """"10:05 AM" -> "10:05", "01:20 PM" -> "13:20"."""
    if not value:
        return None
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?\s*$", value)
    if match is None:
        return None
    hour, minute, half = int(match.group(1)), match.group(2), match.group(3).upper()
    if half == "P" and hour != 12:
        hour += 12
    elif half == "A" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}"


def meetings_of(clob: str | None) -> list[dict[str, Any]]:
    """The meeting rows, one entry per day a pattern meets."""
    if not clob:
        return []
    try:
        rows = json.loads(clob)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []

    meetings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = parse_clock(row.get("SSRMEET_BEGIN_TIME"))
        end = parse_clock(row.get("SSRMEET_END_TIME"))
        if not start or not end:
            continue  # an online or arranged section has no clock
        building = (row.get("SSRMEET_BLDG_CODE") or "").strip() or None
        room = (row.get("SSRMEET_ROOM_CODE") or "").strip() or None
        for column, day in _DAY_COLUMNS.items():
            if row.get(column):
                meetings.append(
                    {
                        "day": day,
                        "start": start,
                        "end": end,
                        "building": building,
                        "room": room,
                    }
                )
    return meetings


def primary_instructor(raw: str | None) -> str | None:
    """The instructor marked "(P)", or the first one listed."""
    if not raw:
        return None
    try:
        staff = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(staff, list) or not staff:
        return None
    names = [str(s.get("NAME", "")).strip() for s in staff if isinstance(s, dict)]
    names = [n for n in names if n]
    if not names:
        return None
    primary = next((n for n in names if n.endswith("(P)")), names[0])
    return re.sub(r"\s*\((P|S)\)\s*$", "", primary).strip() or None


def _int(value: Any) -> int | None:
    """Banner writes "NA" for a seat count it will not disclose."""
    text_value = str(value or "").strip()
    if not text_value or text_value.upper() == "NA":
        return None
    try:
        return int(text_value)
    except ValueError:
        return None


def delivery_of(record: dict[str, Any]) -> str | None:
    kind = (record.get("SWV_CLASS_SEARCH_INST_TYPE") or "").strip().lower()
    if "web" in kind or "distance" in kind:
        return "WEB"
    if "hybrid" in kind or "mixed" in kind:
        return "HYBRID"
    return "F2F" if kind else None


def is_honors(record: dict[str, Any]) -> bool:
    title = (record.get("SWV_CLASS_SEARCH_TITLE") or "").upper()
    attributes = (record.get("SWV_CLASS_SEARCH_ATTRIBUTES") or "").upper()
    return title.startswith("HNR") or "HONORS" in attributes


def parse_records(
    raw: list[dict[str, Any]],
) -> tuple[list[ParsedRow], dict[str, int], dict[tuple[str, str], str]]:
    rows: list[ParsedRow] = []
    skipped: dict[str, int] = {}
    titles: dict[tuple[str, str], str] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for record in raw:
        code = str(record.get("SWV_CLASS_SEARCH_TERM") or "").strip()
        term = term_name(code)
        if term is None:
            skip("unparsed_term")
            continue
        dept = (record.get("SWV_CLASS_SEARCH_SUBJECT") or "").strip().upper()
        number = (record.get("SWV_CLASS_SEARCH_COURSE") or "").strip().upper()
        if not dept or not number:
            skip("no_course")
            continue
        title = (record.get("SWV_CLASS_SEARCH_TITLE") or "").strip()
        if title:
            titles.setdefault((dept, number), title)
        rows.append(
            ParsedRow(
                term=term,
                dept=dept,
                number=number,
                section_code=(record.get("SWV_CLASS_SEARCH_SECTION") or "").strip(),
                instructor=primary_instructor(record.get("SWV_CLASS_SEARCH_INSTRCTR_JSON")),
                campus=campus_of(code),
                delivery=delivery_of(record),
                honors=is_honors(record),
                seats=_int(record.get("SWV_CLASS_SEARCH_MAX_ENRL")),
                seats_open=_int(record.get("SWV_CLASS_SEARCH_SEATS_AVAIL")),
                meetings=meetings_of(record.get("SWV_CLASS_SEARCH_JSON_CLOB")),
            )
        )
    return rows, skipped, titles


async def link_instructors(rows: list[ParsedRow]) -> tuple[int, int]:
    """Rewrite scraped instructor names to the ones already in the database.

    The schedule names staff in full ("Jacqueline D. Knoop"); the grade reports
    abbreviate ("KNOOP J"). persist() resolves on an exact canonical key, so
    the match is made here, with the stored name as the target and the scraped
    names as candidates -- the direction that keeps an initial from matching
    the wrong person.
    """
    scraped = {row.instructor for row in rows if row.instructor}
    if not scraped:
        return 0, 0
    candidates = {name: name for name in scraped}

    async with session_scope() as session:
        stored = (
            await session.execute(text("select id, full_name from instructors"))
        ).all()

    renames: dict[str, str] = {}
    for _id, full_name in stored:
        outcome = resolve_name(str(full_name), candidates)
        if outcome.match is not None:
            # First stored name to claim a scraped name keeps it.
            renames.setdefault(str(outcome.match.value), str(full_name))

    linked = 0
    for row in rows:
        if row.instructor and row.instructor in renames:
            row.instructor = renames[row.instructor]
            linked += 1
    log.info("%s sections linked to a known instructor", linked)
    return linked, len(scraped)


async def create_missing_courses(rows: list[ParsedRow], titles: dict[tuple[str, str], str]) -> int:
    """Add courses the schedule offers that the catalog scrape never had.

    The catalog covers the undergraduate bulletin; the schedule also carries
    graduate research, internship and directed-studies numbers (691, 684, 685
    and the like). Without these the loader drops about a quarter of the
    sections on the floor, which reads as missing data rather than as a
    catalog that stops where the bulletin does.
    """
    async with session_scope() as session:
        have = {
            (str(a), str(b))
            for a, b in (
                await session.execute(text("select upper(dept), upper(number) from courses"))
            ).all()
        }
        missing = {(r.dept, r.number) for r in rows} - have
        if not missing:
            return 0
        payload = [
            {
                "dept": dept,
                "number": number,
                "title": titles.get((dept, number)),
                "honors": False,
            }
            for dept, number in sorted(missing)
        ]
        await session.execute(
            text(
                "insert into courses (dept, number, title, honors) "
                "values (cast(:dept as text), cast(:number as text), "
                "cast(:title as text), cast(:honors as boolean)) "
                "on conflict on constraint courses_identity do nothing"
            ),
            payload,
        )
        await session.commit()
    log.info("created %s courses the catalog did not have", len(payload))
    return len(payload)


async def load(path: Path, *, limit: int | None = None) -> Stats:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if limit is not None:
        raw = raw[:limit]
    rows, skipped, titles = parse_records(raw)
    await create_missing_courses(rows, titles)
    _, distinct = await link_instructors(rows)
    log.info(
        "%s sections parsed; %s of %s distinct instructor names matched someone on record",
        len(rows),
        len({r.instructor for r in rows if r.instructor}),
        distinct,
    )
    stats = await persist(rows)
    for reason in skipped:
        stats.skip(reason)
    with_times = sum(1 for r in rows if r.meetings)
    log.info(
        "%s of %s sections carry real meeting times (%s online or arranged)",
        with_times,
        len(rows),
        len(rows) - with_times,
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    configure_logging()
    for path in args.paths:
        log.info("loading %s", path)
        stats = asyncio.run(load(path, limit=args.limit))
        log.info("done %s", stats.report())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
