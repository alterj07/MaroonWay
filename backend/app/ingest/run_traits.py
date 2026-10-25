"""Ask Jev what each professor's reviews actually say.

    python -m app.ingest.run_traits --limit 5 --dry-run
    python -m app.ingest.run_traits --limit 50

The planning doc wants students to choose on "types of teachers and classes --
less quizzes, easier tests, good lecturer". Those are decisions, not prose:
every one has a fixed answer set. So they go to Jev rather than to an LLM, and
come back as typed columns the scheduler can weight.

Per professor, and per professor-and-course where enough reviews mention the
course, so the doc's other requirement holds: the class is described from the
reviews of that class, while the teaching style comes from all of them.

Resumable through the unique constraint on (instructor, course,
question_version) -- bump QUESTION_VERSION in app/services/preferences.py's
TRAIT_QUESTIONS and a re-run refreshes everything.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import instructor_traits
from app.services.jev import Decider, HeuristicDecider, build_decider
from app.services.preferences import TRAIT_QUESTIONS, Traits

log = logging.getLogger("ingest.traits")

#: Bump when TRAIT_QUESTIONS changes, so old answers are refreshed not reused.
QUESTION_VERSION = "t1"
TRAIT_FIELDS = (
    "lots_of_quizzes",
    "exam_difficulty",
    "lecture_quality",
    "attendance_taken",
    "extra_credit",
    "heavy_workload",
    "grades_generously",
)

_insert = pg_insert(instructor_traits)
_UPSERT = _insert.on_conflict_do_update(
    constraint="instructor_traits_identity",
    set_={
        name: getattr(_insert.excluded, name)
        for name in (*TRAIT_FIELDS, "confidence", "model", "review_count", "answers", "decided_at")
    },
)

_CANDIDATES = text(
    """
    select i.id as instructor_id, i.full_name, i.rmp_id
    from instructors i
    join rmp_professors p on p.rmp_id = i.rmp_id
    where p.num_ratings > 0
      and exists (
            select 1 from rmp_ratings r
             where r.rmp_id = i.rmp_id and r.comment is not null
          )
    order by p.num_ratings desc
    limit cast(:limit as integer)
    """
)

_REVIEWS = text(
    """
    select r.comment, r.class_code, r.course_id, r.rated_at, r.difficulty,
           r.grade, r.attendance_mandatory, r.is_online, r.rating_tags
    from rmp_ratings r
    where r.rmp_id = cast(:rmp_id as bigint)
      and r.comment is not null
      and length(btrim(r.comment)) > 0
    order by r.rated_at desc nulls last
    limit cast(:limit as integer)
    """
)

_EXISTING = text(
    """
    select instructor_id, course_id
    from instructor_traits
    where question_version = cast(:version as text)
    """
)


@dataclass(slots=True)
class Stats:
    professors: int = 0
    instructor_decisions: int = 0
    course_decisions: int = 0
    skipped_existing: int = 0
    skipped_thin: int = 0
    failed: int = 0
    low_confidence: int = 0
    input_tokens: int = 0

    def report(self) -> str:
        return (
            f"professors={self.professors} instructor={self.instructor_decisions}"
            f" course={self.course_decisions} existing={self.skipped_existing}"
            f" thin={self.skipped_thin} failed={self.failed}"
            f" low_confidence={self.low_confidence} input_tokens={self.input_tokens}"
        )


def build_state(name: str, reviews: list[dict[str, Any]], course: str | None = None) -> dict:
    """What Jev is shown.

    A JSON object rather than prose: the structured fields the scrape already
    captured (the student's grade, whether attendance was taken, the tags) are
    evidence in their own right, and Jev accepts an object as state.
    """
    return {
        "professor": name,
        "course": course,
        "review_count": len(reviews),
        "reviews": [
            {
                "comment": row["comment"],
                "class": row.get("class_code"),
                "difficulty": float(row["difficulty"]) if row.get("difficulty") else None,
                "student_grade": row.get("grade"),
                "attendance_mandatory": row.get("attendance_mandatory"),
                "online": row.get("is_online"),
                "tags": row.get("rating_tags"),
            }
            for row in reviews
        ],
    }


def to_row(
    *,
    instructor_id: int,
    course_id: int | None,
    traits: Traits,
    confidence: float | None,
    answers: dict[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instructor_id": instructor_id,
        "course_id": course_id,
        "confidence": confidence,
        "model": traits.engine,
        "question_version": QUESTION_VERSION,
        "review_count": traits.review_count,
        "answers": answers,
        "decided_at": datetime.now(timezone.utc),
    }
    for field_name in TRAIT_FIELDS:
        row[field_name] = getattr(traits, field_name)
    return row


async def decide_for(
    decider: Decider,
    *,
    name: str,
    reviews: list[dict[str, Any]],
    course: str | None = None,
) -> tuple[Traits, float | None, dict[str, Any]]:
    decisions = await decider.decide(build_state(name, reviews, course), TRAIT_QUESTIONS)
    traits = Traits.from_decisions(decisions, review_count=len(reviews))
    confidences = [
        a.confidence for a in decisions.answers.values() if a.confidence is not None
    ]
    confidence = sum(confidences) / len(confidences) if confidences else None
    answers = {
        name_: {"value": a.value, "confidence": a.confidence, "kind": a.kind}
        for name_, a in decisions.answers.items()
    }
    return traits, confidence, answers


async def run(
    *,
    limit: int,
    dry_run: bool,
    stub: bool,
    min_reviews: int,
    min_course_reviews: int,
    include_courses: bool,
) -> Stats:
    settings = get_settings()
    stats = Stats()
    decider: Decider = (
        HeuristicDecider()
        if stub
        else build_decider(settings)
    )
    log.info("deciding with %s", decider.model)

    async with session_scope() as session:
        candidates = (await session.execute(_CANDIDATES, {"limit": limit})).mappings().all()
        existing = {
            (int(row[0]), int(row[1]) if row[1] is not None else None)
            for row in (await session.execute(_EXISTING, {"version": QUESTION_VERSION})).all()
        }
        log.info("%d professors with comments; %d decisions already made", len(candidates), len(existing))

        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            stats.professors += 1
            instructor_id = int(candidate["instructor_id"])
            reviews = [
                dict(r)
                for r in (
                    await session.execute(
                        _REVIEWS,
                        {"rmp_id": candidate["rmp_id"], "limit": settings.trait_max_reviews},
                    )
                )
                .mappings()
                .all()
            ]
            if len(reviews) < min_reviews:
                stats.skipped_thin += 1
                continue

            # The professor overall: every review, which is what the doc means
            # by keeping the general teaching style.
            if (instructor_id, None) in existing:
                stats.skipped_existing += 1
            elif dry_run:
                stats.instructor_decisions += 1
            else:
                try:
                    traits, confidence, answers = await decide_for(
                        decider, name=candidate["full_name"], reviews=reviews
                    )
                except Exception as exc:  # noqa: BLE001 - one professor is not the run
                    stats.failed += 1
                    log.warning("decision failed for %s: %s", candidate["full_name"], exc)
                    continue
                if confidence is not None and confidence < 0.45:
                    stats.low_confidence += 1
                rows.append(
                    to_row(
                        instructor_id=instructor_id,
                        course_id=None,
                        traits=traits,
                        confidence=confidence,
                        answers=answers,
                    )
                )
                stats.instructor_decisions += 1

            if not include_courses:
                continue

            # And per course, from only that course's reviews.
            by_course: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for review in reviews:
                if review.get("course_id"):
                    by_course[int(review["course_id"])].append(review)
            for course_id, course_reviews in by_course.items():
                if len(course_reviews) < min_course_reviews:
                    stats.skipped_thin += 1
                    continue
                if (instructor_id, course_id) in existing:
                    stats.skipped_existing += 1
                    continue
                if dry_run:
                    stats.course_decisions += 1
                    continue
                try:
                    traits, confidence, answers = await decide_for(
                        decider,
                        name=candidate["full_name"],
                        reviews=course_reviews,
                        course=course_reviews[0].get("class_code"),
                    )
                except Exception as exc:  # noqa: BLE001
                    stats.failed += 1
                    log.warning("course decision failed for %s: %s", candidate["full_name"], exc)
                    continue
                rows.append(
                    to_row(
                        instructor_id=instructor_id,
                        course_id=course_id,
                        traits=traits,
                        confidence=confidence,
                        answers=answers,
                    )
                )
                stats.course_decisions += 1

            if len(rows) >= 200:
                await session.execute(_UPSERT, rows)
                await session.commit()
                log.info("progress %s", stats.report())
                rows = []

        if dry_run:
            log.info("DRY RUN %s (no calls, nothing written)", stats.report())
            return stats

        if rows:
            await session.execute(_UPSERT, rows)
            await session.commit()
        if stats.instructor_decisions or stats.course_decisions:
            version = await bump_data_version(session)
            log.info("data_version now %d (hot cache invalidated)", version)

    log.info("done %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="professors to consider")
    parser.add_argument("--dry-run", action="store_true", help="count the work, call nothing")
    parser.add_argument("--stub", action="store_true", help="use the keyword fallback")
    parser.add_argument("--min-reviews", type=int, default=3)
    parser.add_argument("--min-course-reviews", type=int, default=2)
    parser.add_argument("--no-courses", action="store_true", help="professor level only")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(
        run(
            limit=args.limit,
            dry_run=args.dry_run,
            stub=args.stub,
            min_reviews=args.min_reviews,
            min_course_reviews=args.min_course_reviews,
            include_courses=not args.no_courses,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
