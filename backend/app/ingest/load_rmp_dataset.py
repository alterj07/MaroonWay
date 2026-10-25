"""Load RateMyProfessors data out of the project's own pipeline output.

    python -m app.ingest.load_rmp_dataset ../Data/output/schedule_dataset.csv --dry-run
    python -m app.ingest.load_rmp_dataset ../Data/output/schedule_dataset.csv

This replaces scraping for everything except refreshes: schedule_dataset.csv
already carries matched professors, their aggregates, and the review text --
split into overall reviews and reviews collected as being about one course.
Its reviews are also richer than the pinned scraper package's parser exposes,
carrying each student's letter grade, their own would-take-again answer, and
the rating tags.

Professor links are taken from the pipeline where it made one, and resolved
here where it did not: the grade reports name instructors as "RODRIGUEZ C",
which app/services/names.py can match against "Christopher Rodriguez" on
surname plus initial. Anything genuinely ambiguous is recorded as such rather
than guessed, and every decision lands in name_links with its method and
confidence.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import name_links, rmp_professors, rmp_ratings
from app.services.names import DEFAULT_FLOOR, normalize_name, resolve_name
from app.services.rmp import normalize_rating, parse_rmp_date

log = logging.getLogger("ingest.rmp_dataset")

BATCH_SIZE = 1_000
#: The review JSON blobs are large; the default field limit rejects them.
CSV_FIELD_LIMIT = 10_000_000
PIPELINE_MATCHED = "matched_name_department"

_professor_insert = pg_insert(rmp_professors)
_PROFESSOR_UPSERT = _professor_insert.on_conflict_do_update(
    index_elements=[rmp_professors.c.rmp_id],
    set_={
        name: getattr(_professor_insert.excluded, name)
        for name in (
            "first_name",
            "last_name",
            "full_name",
            "department",
            "school_id",
            "avg_rating",
            "avg_difficulty",
            "num_ratings",
            "would_take_again_percent",
            "rmp_url",
            "reviews_window_start",
            "reviews_window_end",
            "fetched_at",
            "details_fetched_at",
        )
    },
)

_rating_insert = pg_insert(rmp_ratings)
_RATING_UPSERT = _rating_insert.on_conflict_do_update(
    index_elements=[rmp_ratings.c.rmp_rating_id],
    index_where=rmp_ratings.c.rmp_rating_id.isnot(None),
    set_={
        name: getattr(_rating_insert.excluded, name)
        for name in (
            "course_id",
            "class_code",
            "comment",
            "helpful",
            "clarity",
            "difficulty",
            "rated_at",
            "is_online",
            "attendance_mandatory",
            "textbook_use",
            "is_for_credit",
            "grade",
            "would_take_again",
            "rating_tags",
            "thumbs_up",
            "thumbs_down",
            "course_match_status",
            "raw",
        )
    },
)

_link_insert = pg_insert(name_links)
_LINK_UPSERT = _link_insert.on_conflict_do_update(
    constraint="name_links_identity",
    set_={
        name: getattr(_link_insert.excluded, name)
        for name in ("instructor_id", "rmp_id", "method", "confidence", "normalized_name")
    },
)


@dataclass(slots=True)
class Stats:
    rows_read: int = 0
    professors: int = 0
    reviews: int = 0
    course_reviews: int = 0
    linked: int = 0
    link_reasons: Counter = field(default_factory=Counter)
    unmatched_names: list[str] = field(default_factory=list)

    def report(self) -> str:
        reasons = " ".join(f"{k}={v}" for k, v in sorted(self.link_reasons.items()))
        return (
            f"rows={self.rows_read} professors={self.professors} reviews={self.reviews}"
            f" (course-tagged {self.course_reviews}) linked={self.linked}"
            + (f" [{reasons}]" if reasons else "")
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    if not full_name:
        return None, None
    parts = full_name.split()
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], " ".join(parts[1:])


def _reviews(blob: str | None) -> list[dict[str, Any]]:
    if not blob or blob.strip() in ("", "[]"):
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


@dataclass(slots=True)
class Extract:
    """Everything read out of the CSV, before any database work."""

    professors: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: Keyed on the review's own id, so the same review appearing under both the
    #: overall and the course-specific list is stored once.
    reviews: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: Reviews with no id of their own, keyed by their content.
    idless_reviews: list[dict[str, Any]] = field(default_factory=list)
    pipeline_links: dict[str, tuple[int, float | None]] = field(default_factory=dict)
    instructor_names: set[str] = field(default_factory=set)
    roster: dict[str, int] = field(default_factory=dict)


def extract(path: Path, *, limit: int | None, stats: Stats) -> Extract:
    csv.field_size_limit(CSV_FIELD_LIMIT)
    out = Extract()

    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle):
            if limit is not None and stats.rows_read >= limit:
                break
            stats.rows_read += 1

            instructor = _text(row.get("instructor_name"))
            if instructor:
                out.instructor_names.add(instructor)

            rmp_id = _int(row.get("rmp_professor_id"))
            if rmp_id is None:
                continue

            name = _text(row.get("rmp_name"))
            if name:
                out.roster[name] = rmp_id
            first, last = _split_name(name)
            out.professors[rmp_id] = {
                "rmp_id": rmp_id,
                "first_name": first,
                "last_name": last,
                "full_name": name,
                "department": _text(row.get("departments")),
                "school_id": None,
                "avg_rating": _float(row.get("rmp_rating")),
                "avg_difficulty": _float(row.get("rmp_difficulty")),
                "num_ratings": _int(row.get("rmp_review_count")) or 0,
                "would_take_again_percent": _float(row.get("rmp_would_take_again_pct")),
                "rmp_url": _text(row.get("rmp_url")),
                "reviews_window_start": parse_rmp_date(row.get("reviews_window_start")),
                "reviews_window_end": parse_rmp_date(row.get("reviews_window_end")),
                "fetched_at": parse_rmp_date(row.get("rmp_fetched_at")) or datetime.now().astimezone(),
                "details_fetched_at": parse_rmp_date(row.get("rmp_reviews_fetched_at")),
            }

            if instructor and (row.get("match_status") or "") == PIPELINE_MATCHED:
                out.pipeline_links[instructor] = (rmp_id, _float(row.get("match_confidence")))

            subject = _text(row.get("subject"))
            number = _text(row.get("course_number"))
            course_key = (subject.upper(), number.upper()) if subject and number else None

            for blob, course_scoped in (
                (row.get("rmp_reviews_past_year_json"), False),
                (row.get("rmp_course_reviews_past_year_json"), True),
            ):
                for review in _reviews(blob):
                    record = normalize_rating(review, rmp_id)
                    payload = {
                        "rmp_id": rmp_id,
                        "rmp_rating_id": record.rating_id,
                        "class_code": record.class_code,
                        "comment": record.comment,
                        "helpful": record.helpful,
                        "clarity": record.clarity,
                        "difficulty": record.difficulty,
                        "rated_at": record.rated_at,
                        "is_online": record.is_online,
                        "attendance_mandatory": record.attendance_mandatory,
                        "textbook_use": record.textbook_use,
                        "is_for_credit": record.is_for_credit,
                        "grade": record.grade,
                        "would_take_again": record.would_take_again,
                        "rating_tags": record.rating_tags,
                        "thumbs_up": record.thumbs_up,
                        "thumbs_down": record.thumbs_down,
                        "course_match_status": record.course_match_status,
                        "raw": record.raw,
                        "_course_key": course_key if course_scoped else None,
                    }
                    if record.rating_id is None:
                        out.idless_reviews.append(payload)
                        continue
                    existing = out.reviews.get(record.rating_id)
                    # The course-scoped copy is the more informative one: it is
                    # what tells us which course the review is actually about.
                    if existing is None or (
                        payload["_course_key"] and not existing["_course_key"]
                    ):
                        out.reviews[record.rating_id] = payload
    return out


async def _course_ids(session: AsyncSession) -> dict[tuple[str, str], int]:
    rows = (await session.execute(text("select id, upper(dept), upper(number) from courses"))).all()
    return {(row[1], row[2]): int(row[0]) for row in rows}


async def _instructors(session: AsyncSession) -> dict[str, tuple[int, int | None]]:
    rows = (
        await session.execute(text("select id, full_name, rmp_id from instructors"))
    ).all()
    return {str(row[1]): (int(row[0]), row[2]) for row in rows}


async def link_instructors(
    session: AsyncSession,
    data: Extract,
    *,
    floor: float,
    stats: Stats,
) -> None:
    """Attach each instructor row to an RMP professor, recording how."""
    instructors = await _instructors(session)
    taken = {rmp_id for _, (_, rmp_id) in instructors.items() if rmp_id is not None}
    links: list[dict[str, Any]] = []

    for name in sorted(data.instructor_names):
        entry = instructors.get(name)
        if entry is None:
            stats.link_reasons["no_instructor_row"] += 1
            continue
        instructor_id, existing = entry
        if existing is not None:
            stats.link_reasons["already_linked"] += 1
            continue

        if (pipeline := data.pipeline_links.get(name)) is not None:
            rmp_id, confidence = pipeline
            method, reason, score = "pipeline", "pipeline", confidence or 100.0
        else:
            outcome = resolve_name(name, data.roster, floor=floor)
            reason = outcome.reason
            if outcome.match is None:
                stats.link_reasons[reason] += 1
                if reason in ("ambiguous", "initial_mismatch", "no_match"):
                    stats.unmatched_names.append(name)
                continue
            rmp_id, method, score = int(outcome.match.value), outcome.match.method, outcome.match.score

        # instructors.rmp_id is unique: two instructor rows resolving to one
        # professor is a tie we must not break silently.
        if rmp_id in taken:
            stats.link_reasons["rmp_id_already_taken"] += 1
            stats.unmatched_names.append(name)
            continue

        taken.add(rmp_id)
        stats.linked += 1
        stats.link_reasons[reason] += 1
        links.append(
            {
                "source": "grades_csv",
                "source_name": name,
                "normalized_name": normalize_name(name),
                "instructor_id": instructor_id,
                "rmp_id": rmp_id,
                "method": method,
                "confidence": round(float(score), 2),
            }
        )

    for start in range(0, len(links), BATCH_SIZE):
        batch = links[start : start + BATCH_SIZE]
        await session.execute(_LINK_UPSERT, batch)
        await session.execute(
            text(
                """
                update instructors
                   set rmp_id = cast(:rmp_id as bigint)
                 where id = cast(:instructor_id as bigint)
                   and rmp_id is null
                """
            ),
            [{"rmp_id": row["rmp_id"], "instructor_id": row["instructor_id"]} for row in batch],
        )
    await session.commit()


async def load(
    path: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    floor: float = DEFAULT_FLOOR,
) -> Stats:
    stats = Stats()
    log.info("reading %s", path)
    data = extract(path, limit=limit, stats=stats)
    stats.professors = len(data.professors)
    stats.reviews = len(data.reviews) + len(data.idless_reviews)
    stats.course_reviews = sum(1 for r in data.reviews.values() if r["_course_key"])
    log.info(
        "extracted %d professors, %d distinct reviews (%d course-tagged), "
        "%d instructor names, roster of %d",
        stats.professors,
        stats.reviews,
        stats.course_reviews,
        len(data.instructor_names),
        len(data.roster),
    )

    if dry_run:
        for payload in list(data.professors.values())[:3]:
            log.info(
                "sample professor %s (%s) rating=%s reviews=%s",
                payload["rmp_id"],
                payload["full_name"],
                payload["avg_rating"],
                payload["num_ratings"],
            )
        log.info("DRY RUN %s (nothing written)", stats.report())
        return stats

    async with session_scope() as session:
        professors = list(data.professors.values())
        for start in range(0, len(professors), BATCH_SIZE):
            await session.execute(_PROFESSOR_UPSERT, professors[start : start + BATCH_SIZE])
        await session.commit()
        log.info("wrote %d professors", len(professors))

        course_ids = await _course_ids(session)
        reviews = list(data.reviews.values())
        resolved = 0
        for payload in reviews:
            key = payload.pop("_course_key")
            payload["course_id"] = course_ids.get(key) if key else None
            resolved += payload["course_id"] is not None
        for start in range(0, len(reviews), BATCH_SIZE):
            await session.execute(_RATING_UPSERT, reviews[start : start + BATCH_SIZE])
            if start and start % (BATCH_SIZE * 10) == 0:
                await session.commit()
                log.info("wrote %d reviews", start)
        await session.commit()
        log.info("wrote %d reviews, %d attached to a course", len(reviews), resolved)

        await link_instructors(session, data, floor=floor, stats=stats)
        version = await bump_data_version(session)
        log.info("data_version now %d (hot cache invalidated)", version)

    log.info("done %s", stats.report())
    if stats.unmatched_names:
        log.info("%d instructor names still unmatched", len(stats.unmatched_names))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="rows to read")
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(load(args.path, dry_run=args.dry_run, limit=args.limit, floor=args.floor))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
