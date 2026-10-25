"""Generate a demonstration sections file, so the scheduler has something to chew.

    python -m app.ingest.make_demo_sections --out out/demo_sections.csv
    python -m app.ingest.load_sections out/demo_sections.csv

A&M closed its public course API in 2023 and the replacement needs a student
login, so no real meeting times are available to this project yet. This builds
a plausible term from data that *is* real -- actual courses, actual instructors
who actually taught them, their actual ratings -- and pairs them with standard
A&M meeting patterns.

The times are invented. That is why the term is labelled "DEMO <term>": nothing
here should ever be mistaken for the registrar's schedule. Replace it by running
load_sections.py against a real export; no other code changes.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path

from sqlalchemy import text

from app.ingest.common import configure_logging, session_scope

log = logging.getLogger("ingest.demo")

#: A&M's standard patterns: 50 minutes three days a week, 75 minutes twice.
MWF_SLOTS = ["08:00", "09:10", "10:20", "11:30", "12:40", "13:50", "15:00", "16:10"]
TR_SLOTS = ["08:00", "09:35", "11:10", "12:45", "14:20", "15:55"]
BUILDINGS = ["ZACH", "HRBB", "BLOC", "HELD", "ARCB", "MPHY", "CHEN", "ETB"]

_CANDIDATES = text(
    """
    select
        upper(c.dept)  as dept,
        c.number       as number,
        i.full_name    as instructor,
        ics.adj_rating as rating,
        ics.section_count
    from instructor_course_scores ics
    join courses c     on c.id = ics.course_id
    join instructors i on i.id = ics.instructor_id
    where i.rmp_id is not null
      and ics.section_count > 0
    order by ics.section_count desc, ics.adj_rating desc
    limit cast(:limit as integer)
    """
)


def add_minutes(clock: str, minutes: int) -> str:
    hours, mins = (int(part) for part in clock.split(":"))
    total = hours * 60 + mins + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


async def build(*, term: str, out: Path, courses: int, per_course: int) -> int:
    async with session_scope() as session:
        rows = (await session.execute(_CANDIDATES, {"limit": courses * per_course * 3})).mappings().all()

    by_course: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["dept"], row["number"])
        if len(by_course.setdefault(key, [])) < per_course:
            by_course[key].append(dict(row))
        if len(by_course) >= courses and all(len(v) >= 1 for v in by_course.values()):
            if sum(len(v) for v in by_course.values()) >= courses * per_course:
                break

    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["term", "subject", "number", "section", "instructor", "days",
             "start_time", "end_time", "building", "room", "campus", "delivery",
             "honors", "seats", "seats_open"]
        )
        for index, ((dept, number), teachers) in enumerate(sorted(by_course.items())):
            for offset, teacher in enumerate(teachers):
                pattern = "MWF" if (index + offset) % 3 != 2 else "TR"
                slots = MWF_SLOTS if pattern == "MWF" else TR_SLOTS
                start = slots[(index * 2 + offset) % len(slots)]
                end = add_minutes(start, 50 if pattern == "MWF" else 75)
                writer.writerow(
                    [
                        term, dept, number, f"{5}{offset:02d}", teacher["instructor"],
                        pattern, start, end,
                        BUILDINGS[(index + offset) % len(BUILDINGS)],
                        f"{100 + (index * 7 + offset) % 300}",
                        "College Station", "F2F", "false", 60, 12,
                    ]
                )
                written += 1

    log.info("wrote %d demo sections across %d courses -> %s", written, len(by_course), out)
    log.warning(
        "the MEETING TIMES in this file are invented; the courses, instructors "
        "and ratings are real. The term is labelled %r so it cannot be mistaken "
        "for the registrar's schedule.",
        term,
    )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("out/demo_sections.csv"))
    parser.add_argument("--term", default="DEMO FALL 2026")
    parser.add_argument("--courses", type=int, default=60)
    parser.add_argument("--per-course", type=int, default=3)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(
        build(term=args.term, out=args.out, courses=args.courses, per_course=args.per_course)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
