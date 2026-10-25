"""Load the datapoints the dataset carries that the grade reports do not.

The grade reports (``sections_all.csv``) are per-section counts: they know the
college and department but not which campus the section ran on, and they say
nothing about a course's level. ``schedule_dataset.csv`` knows all three per
instructor-course, and it also records *which terms* each instructor taught
each course -- the only evidence available about who is likely to teach it
again, and so the only honest basis for proposing next term's sections.

Run it after load_grades and load_catalog, both of which create the rows this
fills in::

    python -m app.ingest.load_extras ../Data/output/schedule_dataset.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.ingest.load_grades import normalize_campus
from app.ingest.load_rmp_dataset import CSV_FIELD_LIMIT
from app.models import instructor_course_terms
from app.services.names import canonical_key
from app.services.terms import parse_term

log = logging.getLogger("ingest.extras")

BATCH_SIZE = 1000


@dataclass
class Stats:
    rows: int = 0
    campus_set: int = 0
    level_set: int = 0
    terms_loaded: int = 0
    departments_set: int = 0
    skipped: Counter[str] = field(default_factory=Counter)

    def skip(self, reason: str) -> None:
        self.skipped[reason] += 1


def _text_value(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _terms(raw: str | None) -> list[str]:
    """The term names from a grade_terms_json cell, e.g. ["FALL 2023", ...]."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return []
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


async def _id_maps(
    session: AsyncSession,
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    instructors = {
        str(row[1]): int(row[0])
        for row in (
            await session.execute(text("select id, canonical_key from instructors"))
        ).all()
    }
    courses: dict[tuple[str, str], int] = {}
    for row in (
        await session.execute(
            text("select id, upper(dept), upper(number), honors from courses order by honors")
        )
    ).all():
        # Prefer the non-honors row when a course exists in both forms: the
        # dataset does not distinguish them, so the plain section is the safer
        # default to attribute a campus or a teaching term to.
        courses.setdefault((str(row[1]), str(row[2])), int(row[0]))
    return instructors, courses


async def load(path: Path, limit: int | None = None) -> Stats:
    import csv

    # The dataset's review columns hold JSON blobs far past the 128 KiB default.
    csv.field_size_limit(CSV_FIELD_LIMIT)

    stats = Stats()
    campus_rows: list[dict[str, object]] = []
    level_rows: list[dict[str, object]] = []
    term_rows: list[dict[str, object]] = []
    seen_terms: set[tuple[int, int, str]] = set()

    async with session_scope() as session:
        instructor_ids, course_ids = await _id_maps(session)

        with path.open(newline="", encoding="utf-8") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                if limit is not None and index >= limit:
                    break
                stats.rows += 1

                dept = (_text_value(row.get("subject")) or "").upper()
                number = (_text_value(row.get("course_number")) or "").upper()
                course_id = course_ids.get((dept, number))
                if course_id is None:
                    stats.skip("unknown_course")
                    continue

                name = _text_value(row.get("instructor_name"))
                instructor_id = instructor_ids.get(canonical_key(name)) if name else None
                if instructor_id is None:
                    stats.skip("unknown_instructor")
                    continue

                campus = normalize_campus(_text_value(row.get("campus")))
                if campus:
                    campus_rows.append(
                        {"i": instructor_id, "c": course_id, "campus": campus}
                    )

                level = _text_value(row.get("level"))
                if level:
                    level_rows.append({"c": course_id, "level": level})

                for term in _terms(row.get("grade_terms_json")):
                    key = (instructor_id, course_id, term)
                    if key in seen_terms:
                        continue
                    seen_terms.add(key)
                    parsed = parse_term(term)
                    term_rows.append(
                        {
                            "instructor_id": instructor_id,
                            "course_id": course_id,
                            "term": term,
                            "term_year": parsed.year if parsed else None,
                            "term_season": parsed.season if parsed else None,
                        }
                    )

        # Campus, onto the grade rows for that instructor and course.
        campus_sql = text(
            """
            update course_grades
               set campus = cast(:campus as text)
             where instructor_id = cast(:i as bigint)
               and course_id = cast(:c as bigint)
               and campus is null
            """
        )
        for start in range(0, len(campus_rows), BATCH_SIZE):
            batch = campus_rows[start : start + BATCH_SIZE]
            await session.execute(campus_sql, batch)
            stats.campus_set += len(batch)
        await session.commit()

        level_sql = text(
            """
            update courses
               set level = cast(:level as text)
             where id = cast(:c as bigint)
               and level is null
            """
        )
        for start in range(0, len(level_rows), BATCH_SIZE):
            batch = level_rows[start : start + BATCH_SIZE]
            await session.execute(level_sql, batch)
            stats.level_set += len(batch)
        await session.commit()

        insert_terms = pg_insert(instructor_course_terms).on_conflict_do_nothing(
            index_elements=[
                instructor_course_terms.c.instructor_id,
                instructor_course_terms.c.course_id,
                instructor_course_terms.c.term,
            ]
        )
        for start in range(0, len(term_rows), BATCH_SIZE):
            batch = term_rows[start : start + BATCH_SIZE]
            await session.execute(insert_terms, batch)
            stats.terms_loaded += len(batch)
        await session.commit()

        # An instructor's department, from the department the grade reports
        # filed most of their sections under. The dataset only names one for
        # the fraction of instructors matched to RateMyProfessors.
        result = await session.execute(
            text(
                """
                with ranked as (
                    select instructor_id,
                           department,
                           row_number() over (
                               partition by instructor_id
                               order by count(*) desc, department
                           ) as rn
                      from course_grades
                     where instructor_id is not null
                       and department is not null
                  group by instructor_id, department
                )
                update instructors i
                   set department = ranked.department
                  from ranked
                 where ranked.rn = 1
                   and ranked.instructor_id = i.id
                   and i.department is null
                """
            )
        )
        stats.departments_set = result.rowcount or 0
        await session.commit()

        version = await bump_data_version(session)
        log.info("data_version now %s (hot cache invalidated)", version)

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    configure_logging()
    stats = asyncio.run(load(args.path, args.limit))
    detail = (
        " [" + " ".join(f"{k}={v}" for k, v in sorted(stats.skipped.items())) + "]"
        if stats.skipped
        else ""
    )
    log.info(
        "done rows=%s campus=%s level=%s teaching_terms=%s departments=%s%s",
        stats.rows,
        stats.campus_set,
        stats.level_set,
        stats.terms_loaded,
        stats.departments_set,
        detail,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
