"""Load the A&M course catalog.

    python -m app.ingest.load_catalog ../Data/courses.csv

Gives every course its title, credits, description and -- the planning doc's
"Prereqs" requirement -- its prerequisite text. Courses created earlier by the
grades loader are filled in rather than duplicated, so the order of the two
loaders does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ingest.columns import norm_header, split_course_code
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import courses

log = logging.getLogger("ingest.catalog")

BATCH_SIZE = 500

_insert = pg_insert(courses)
_UPDATABLE = ("title", "credits", "description", "prereq_text", "coreq_text", "is_honors_dept")
#: Only fills blanks: a value already in the table is not overwritten by a
#: later catalog scrape that happens to have less detail.
_UPSERT = _insert.on_conflict_do_update(
    constraint="courses_identity",
    set_={name: getattr(_insert.excluded, name) for name in _UPDATABLE},
)


@dataclass(slots=True)
class Stats:
    rows_read: int = 0
    rows_loaded: int = 0
    rows_skipped: int = 0

    def report(self) -> str:
        return f"read={self.rows_read} loaded={self.rows_loaded} skipped={self.rows_skipped}"


def _bool(value: str | None) -> bool | None:
    if not value:
        return None
    return value.strip().lower() in {"true", "1", "yes", "y", "t"}


def _text(value: str | None) -> str | None:
    return value.strip() or None if value else None


def parse_row(row: dict[str, str]) -> dict[str, Any] | None:
    """One catalog row to course fields, or ``None`` if it has no course code."""
    lookup = {norm_header(k): v for k, v in row.items() if k}
    dept = _text(lookup.get("subject"))
    number = _text(lookup.get("number"))
    if not (dept and number):
        split = split_course_code(lookup.get("course"))
        if split is None:
            return None
        dept, number = split
    return {
        "dept": dept.upper(),
        "number": number.upper(),
        "honors": False,
        "title": _text(lookup.get("title")),
        "credits": _text(lookup.get("credits")),
        "description": _text(lookup.get("description")),
        "prereq_text": _text(lookup.get("prereq_text")),
        "coreq_text": _text(lookup.get("coreq_text")),
        "is_honors_dept": _bool(lookup.get("is_honors_dept")),
    }


async def load(path: Path, *, dry_run: bool = False, limit: int | None = None) -> Stats:
    stats = Stats()
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        rows = list(csv.DictReader(handle))

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if limit is not None and stats.rows_read >= limit:
            break
        stats.rows_read += 1
        record = parse_row(row)
        if record is None:
            stats.rows_skipped += 1
            continue
        parsed.append(record)

    # One row per course identity; a catalog with duplicates would otherwise
    # make the upsert hit the same row twice in a single statement.
    deduped: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for record in parsed:
        deduped[(record["dept"], record["number"], record["honors"])] = record
    unique = list(deduped.values())

    if dry_run:
        for record in unique[:3]:
            log.info("sample %s %s - %s", record["dept"], record["number"], record["title"])
        log.info("DRY RUN %s, %d unique courses (nothing written)", stats.report(), len(unique))
        return stats

    async with session_scope() as session:
        for start in range(0, len(unique), BATCH_SIZE):
            batch = unique[start : start + BATCH_SIZE]
            await session.execute(_UPSERT, batch)
            stats.rows_loaded += len(batch)
            if start and start % (BATCH_SIZE * 10) == 0:
                await session.commit()
                log.info("loaded %d courses", stats.rows_loaded)
        await session.commit()
        version = await bump_data_version(session)
        log.info("data_version now %d (hot cache invalidated)", version)

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
