"""Pull RateMyProfessors data into Postgres and link it to the grades CSV names.

    python -m app.ingest.load_rmp --dry-run             # see what the listing holds
    python -m app.ingest.load_rmp --detail-limit 20     # smoke run
    python -m app.ingest.load_rmp                       # listing + matched professors

Two phases, because they cost wildly different amounts:

1. **Listing** -- one paginated crawl of the whole school (~5k professors) gives
   every professor's aggregates: rating, difficulty, would-take-again, rating
   count, and the GraphQL node id. Cheap, so it always runs in full.
2. **Details** -- the comments, one request per professor. By default this runs
   only for professors who matched a name in the grades CSV, most-rated first,
   because those are the only ones MaroonWay can show on a schedule. ``--all``
   overrides that.

Resumable: ``details_fetched_at`` means a run cut short costs nothing to repeat.
Every name link lands in name_links with its method and confidence, and the
leftovers go to out/unmatched_rmp.csv -- a silently mismatched professor is the
worst failure this pipeline has, so it is written down rather than guessed at.

Check A&M's terms of use before crawling the whole school; this is a scraper.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import name_links, rmp_professors, rmp_ratings
from app.services import rmp as rmp_service
from app.services.names import DEFAULT_FLOOR, backend, match_name, normalize_name
from app.services.throttle import TokenBucket

log = logging.getLogger("ingest.rmp")

UNMATCHED_PATH = Path("out/unmatched_rmp.csv")
AGGREGATE_FIELDS = (
    "node_id",
    "first_name",
    "last_name",
    "full_name",
    "department",
    "school_id",
    "avg_rating",
    "avg_difficulty",
    "num_ratings",
    "would_take_again_percent",
    "fetched_at",
)
DETAIL_FIELDS = AGGREGATE_FIELDS + (
    "ratings_distribution",
    "course_codes",
    "details_fetched_at",
)

_professor_insert = pg_insert(rmp_professors)


def _professor_upsert(fields: tuple[str, ...]) -> Any:
    return _professor_insert.on_conflict_do_update(
        index_elements=[rmp_professors.c.rmp_id],
        set_={name: _professor_insert.excluded[name] for name in fields},
    )


_AGGREGATE_UPSERT = _professor_upsert(AGGREGATE_FIELDS)
_DETAIL_UPSERT = _professor_upsert(DETAIL_FIELDS)

#: A posted rating never changes, so a conflict means "already have it".
_RATING_INSERT = pg_insert(rmp_ratings).on_conflict_do_nothing(constraint="rmp_ratings_identity")

_name_link_insert = pg_insert(name_links)
_NAME_LINK_UPSERT = _name_link_insert.on_conflict_do_update(
    constraint="name_links_identity",
    set_={
        name: _name_link_insert.excluded[name]
        for name in ("instructor_id", "rmp_id", "method", "confidence", "normalized_name")
    },
)

_NEEDS_DETAIL = text(
    """
    select p.rmp_id, p.node_id, p.num_ratings
    from rmp_professors p
    where p.num_ratings > 0
      and (p.details_fetched_at is null or p.details_fetched_at < cast(:cutoff as timestamptz))
      and (
            cast(:include_all as boolean)
            or exists (select 1 from instructors i where i.rmp_id = p.rmp_id)
          )
    order by p.details_fetched_at nulls first, p.num_ratings desc
    limit cast(:limit as integer)
    """
)


@dataclass(slots=True)
class Stats:
    listed: int = 0
    aggregates_written: int = 0
    linked: int = 0
    detail_candidates: int = 0
    details_fetched: int = 0
    ratings: int = 0
    failed: int = 0
    unmatched: list[tuple[str, str]] = field(default_factory=list)

    def report(self) -> str:
        return (
            f"listed={self.listed} aggregates={self.aggregates_written} linked={self.linked}"
            f" details={self.details_fetched}/{self.detail_candidates} ratings={self.ratings}"
            f" failed={self.failed} unmatched={len(self.unmatched)}"
        )


def _aggregate_values(record: rmp_service.ProfessorRecord, now: datetime) -> dict[str, Any]:
    return {
        "rmp_id": record.rmp_id,
        "node_id": record.node_id,
        "first_name": record.first_name,
        "last_name": record.last_name,
        "full_name": record.full_name or None,
        "department": record.department,
        "school_id": record.school_id,
        "avg_rating": record.avg_rating,
        "avg_difficulty": record.avg_difficulty,
        "num_ratings": record.num_ratings,
        "would_take_again_percent": record.would_take_again_percent,
        "fetched_at": now,
    }


async def _store_ratings(session: AsyncSession, record: rmp_service.ProfessorRecord) -> int:
    if not record.ratings:
        return 0
    await session.execute(
        _RATING_INSERT,
        [
            {
                "rmp_id": rating.rmp_id,
                "class_code": rating.class_code,
                "comment": rating.comment,
                "helpful": rating.helpful,
                "clarity": rating.clarity,
                "difficulty": rating.difficulty,
                "rated_at": rating.rated_at,
                "is_online": rating.is_online,
                "attendance_mandatory": rating.attendance_mandatory,
                "textbook_use": rating.textbook_use,
                "is_for_credit": rating.is_for_credit,
                "raw": rating.raw,
            }
            for rating in record.ratings
        ],
    )
    return len(record.ratings)


async def _instructor_candidates(session: AsyncSession) -> dict[str, int]:
    """CSV instructors with no RMP id yet, keyed by the name the CSV spelled."""
    rows = (
        await session.execute(text("select id, full_name from instructors where rmp_id is null"))
    ).all()
    return {str(row[1]): int(row[0]) for row in rows}


async def _link_names(
    session: AsyncSession,
    records: list[rmp_service.ProfessorRecord],
    *,
    floor: float,
    stats: Stats,
) -> None:
    """Attach RMP professors to CSV instructor rows where we can tell who is who."""
    candidates = await _instructor_candidates(session)
    log.info("%d CSV instructors need an RMP id", len(candidates))
    if not candidates:
        return

    # Most-rated first: when two professors could claim the same CSV name, the
    # one students actually reviewed is the better bet.
    for record in sorted(records, key=lambda r: r.num_ratings, reverse=True):
        name = record.full_name
        if not name or not candidates:
            continue
        hit = match_name(name, candidates, floor=floor)
        if hit is None:
            if record.num_ratings > 0:
                stats.unmatched.append((name, str(record.rmp_id)))
            continue

        instructor_id = int(hit.value)
        await session.execute(
            text(
                """
                update instructors
                   set rmp_id = cast(:rmp_id as bigint),
                       department = coalesce(department, cast(:department as text))
                 where id = cast(:instructor_id as bigint)
                   and rmp_id is null
                """
            ),
            {
                "rmp_id": record.rmp_id,
                "department": record.department,
                "instructor_id": instructor_id,
            },
        )
        await session.execute(
            _NAME_LINK_UPSERT,
            {
                "source": "rmp",
                "source_name": name,
                "normalized_name": normalize_name(name),
                "instructor_id": instructor_id,
                "rmp_id": record.rmp_id,
                "method": hit.method,
                "confidence": round(hit.score, 2),
            },
        )
        candidates.pop(hit.matched_name, None)
        stats.linked += 1


def _write_unmatched(stats: Stats) -> None:
    if not stats.unmatched:
        return
    UNMATCHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with UNMATCHED_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rmp_name", "rmp_id"])
        writer.writerows(sorted(stats.unmatched))
    log.warning(
        "%d rated RMP professors matched no CSV instructor -> %s",
        len(stats.unmatched),
        UNMATCHED_PATH,
    )


async def _fetch_details(
    session: AsyncSession,
    *,
    limit: int,
    include_all: bool,
    cutoff: datetime,
    rpm: float,
    stats: Stats,
) -> None:
    rows = (
        await session.execute(
            _NEEDS_DETAIL,
            {"cutoff": cutoff, "include_all": include_all, "limit": limit},
        )
    ).all()
    stats.detail_candidates = len(rows)
    if not rows:
        log.info("no professors need comment fetches")
        return
    log.info("fetching comments for %d professors at %.0f/min", len(rows), rpm)

    bucket = TokenBucket(rpm)
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=rmp_service.DEFAULT_TIMEOUT) as client:
        for rmp_id, node_id, _num_ratings in rows:
            await bucket.acquire()
            try:
                if node_id:
                    record = await rmp_service.fetch_professor_by_node_id(
                        str(node_id), client=client
                    )
                else:
                    # No node id (pre-existing row): pay for the package's
                    # HTML-scrape path rather than skipping the professor.
                    record = await rmp_service.fetch_professor(int(rmp_id))
            except Exception as exc:  # noqa: BLE001 - one professor is not the run
                stats.failed += 1
                log.warning("detail fetch failed for %s: %s", rmp_id, exc)
                continue
            if record is None:
                stats.failed += 1
                continue

            values = _aggregate_values(record, now)
            values["ratings_distribution"] = record.ratings_distribution
            values["course_codes"] = record.course_codes
            values["details_fetched_at"] = now
            await session.execute(_DETAIL_UPSERT, values)
            stats.ratings += await _store_ratings(session, record)
            stats.details_fetched += 1

            if stats.details_fetched % 25 == 0:
                await session.commit()
                log.info("progress %s", stats.report())
    await session.commit()


async def load(
    *,
    school_id: str,
    dry_run: bool,
    detail_limit: int,
    refetch_days: int,
    floor: float,
    include_all: bool,
    rpm: float,
    skip_listing: bool,
) -> Stats:
    stats = Stats()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=refetch_days)

    records: list[rmp_service.ProfessorRecord] = []
    if not skip_listing:
        log.info("listing professors for school %s", school_id)
        records = await rmp_service.fetch_all_professors(school_id)
        stats.listed = len(records)
        rated = sum(1 for r in records if r.num_ratings > 0)
        log.info("listing returned %d professors, %d of them rated", stats.listed, rated)

    if dry_run:
        for record in records[:5]:
            log.info(
                "sample rmp_id=%s node=%s name=%s ratings=%s rating=%s",
                record.rmp_id,
                record.node_id,
                record.full_name,
                record.num_ratings,
                record.avg_rating,
            )
        log.info("DRY RUN %s (nothing written, no comment fetches)", stats.report())
        return stats

    async with session_scope() as session:
        if records:
            for start in range(0, len(records), 500):
                batch = records[start : start + 500]
                await session.execute(
                    _AGGREGATE_UPSERT, [_aggregate_values(r, now) for r in batch]
                )
                stats.aggregates_written += len(batch)
            await session.commit()
            log.info("wrote %d professor aggregates", stats.aggregates_written)
            await _link_names(session, records, floor=floor, stats=stats)
            await session.commit()

        if detail_limit > 0:
            await _fetch_details(
                session,
                limit=detail_limit,
                include_all=include_all,
                cutoff=cutoff,
                rpm=rpm,
                stats=stats,
            )

        version = await bump_data_version(session)
        log.info("data_version now %d (hot cache invalidated)", version)

    _write_unmatched(stats)
    log.info("done %s (matcher=%s)", stats.report(), backend())
    return stats


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school-id", default=settings.rmp_school_id)
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=500,
        help="professors to fetch comments for this run (0 = listing only)",
    )
    parser.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="fetch comments for every professor, not just those matched to the CSV",
    )
    parser.add_argument("--rpm", type=float, default=60.0, help="request pacing, per minute")
    parser.add_argument("--dry-run", action="store_true", help="list only, write nothing")
    parser.add_argument("--refetch-days", type=int, default=settings.rmp_refetch_days)
    parser.add_argument("--skip-listing", action="store_true", help="go straight to comments")
    parser.add_argument(
        "--floor", type=float, default=DEFAULT_FLOOR, help="minimum name-match confidence"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(
        load(
            school_id=args.school_id,
            dry_run=args.dry_run,
            detail_limit=args.detail_limit,
            refetch_days=args.refetch_days,
            floor=args.floor,
            include_all=args.include_all,
            rpm=args.rpm,
            skip_listing=args.skip_listing,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
