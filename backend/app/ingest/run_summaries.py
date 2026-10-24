"""Generate the AI comment summaries, in batch.

    python -m app.ingest.run_summaries --limit 5 --dry-run   # read the prompts first
    python -m app.ingest.run_summaries --limit 5             # then spend quota
    python -m app.ingest.run_summaries                       # everything missing

Two summaries per professor, as the planning doc asks: one from all of their
recent comments (general teaching style) and one per class from only that
class's comments (what this course is like).

Resumable by construction: a row already exists for this prompt_version is a
row we skip, so a run cut short by a 429 picks up where it stopped. The window
is the two most recent semesters *present in the data*, not the two before
today, so the same reviews always produce the same window.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.models import summaries as summaries_table
from app.services.summarize import (
    INSTRUCTOR,
    INSTRUCTOR_COURSE,
    PROMPT_VERSION,
    CommentInput,
    GeminiSummarizer,
    StubSummarizer,
    SummaryRequest,
    SummaryResult,
    Summarizer,
    TokenBucket,
    build_prompt,
    estimate_tokens,
    select_comments,
)
from app.services.terms import recent_terms, window_of

log = logging.getLogger("ingest.summaries")

_NON_ALNUM = re.compile(r"[^A-Z0-9]")

_CANDIDATES = text(
    """
    select i.id as instructor_id, i.full_name, i.rmp_id, p.num_ratings
    from instructors i
    join rmp_professors p on p.rmp_id = i.rmp_id
    where p.num_ratings > 0
    order by p.num_ratings desc
    limit cast(:limit as integer)
    """
)

_COMMENTS = text(
    """
    select r.class_code, r.comment, r.difficulty, r.rated_at,
           r.is_online, r.attendance_mandatory
    from rmp_ratings r
    where r.rmp_id = cast(:rmp_id as bigint)
      and r.comment is not null
      and length(btrim(r.comment)) > 0
    order by r.rated_at desc nulls last
    """
)

_EXISTING = text(
    """
    select subject_type, course_id
    from summaries
    where instructor_id = cast(:instructor_id as bigint)
      and prompt_version = cast(:prompt_version as text)
    """
)

_COURSE_CODES = text("select id, upper(dept || number) as code from courses")

_summary_insert = pg_insert(summaries_table)
_SUMMARY_UPSERT = _summary_insert.on_conflict_do_update(
    constraint="summaries_identity",
    set_={
        name: _summary_insert.excluded[name]
        for name in (
            "model",
            "summary_md",
            "facets",
            "window_start",
            "window_end",
            "source_rating_count",
            "generated_at",
        )
    },
)


@dataclass(slots=True)
class Stats:
    professors: int = 0
    instructor_summaries: int = 0
    course_summaries: int = 0
    skipped_existing: int = 0
    skipped_thin: int = 0
    failed: int = 0
    prompt_tokens: int = 0

    def report(self) -> str:
        return (
            f"professors={self.professors} instructor={self.instructor_summaries}"
            f" course={self.course_summaries} existing={self.skipped_existing}"
            f" thin={self.skipped_thin} failed={self.failed}"
            f" est_prompt_tokens={self.prompt_tokens}"
        )


@dataclass(slots=True)
class Job:
    """One summary to produce."""

    instructor_id: int
    subject_type: str
    request: SummaryRequest
    course_id: int | None = None
    window: tuple[datetime, datetime] | None = None


def normalize_code(value: str | None) -> str | None:
    return _NON_ALNUM.sub("", value.upper()) if value else None


def build_jobs(
    *,
    instructor_id: int,
    full_name: str,
    rows: list[dict[str, Any]],
    course_ids: dict[str, int],
    existing: set[tuple[str, int | None]],
    min_comments: int,
    terms_back: int,
    max_comments: int,
    comment_chars: int,
    include_courses: bool,
) -> tuple[list[Job], int]:
    """Decide what to summarise for one professor. Returns (jobs, thin_skips)."""
    dates = [row["rated_at"] for row in rows if row.get("rated_at")]
    terms = recent_terms(dates, terms_back)
    window = window_of(terms)
    labels = [term.label for term in sorted(terms, reverse=True)]

    if window is not None:
        start, end = window
        in_window = [
            row
            for row in rows
            if row.get("rated_at") is not None and start <= row["rated_at"] < end
        ]
    else:  # no usable dates: summarise what we have rather than nothing
        in_window = list(rows)

    jobs: list[Job] = []
    thin = 0

    comments = [
        CommentInput(
            text=row["comment"],
            class_code=row.get("class_code"),
            rated_at=row.get("rated_at"),
            difficulty=float(row["difficulty"]) if row.get("difficulty") is not None else None,
            is_online=row.get("is_online"),
            attendance_mandatory=row.get("attendance_mandatory"),
        )
        for row in in_window
    ]

    if len(comments) < min_comments:
        return [], 1

    if (INSTRUCTOR, None) in existing:
        pass
    else:
        jobs.append(
            Job(
                instructor_id=instructor_id,
                subject_type=INSTRUCTOR,
                window=window,
                request=SummaryRequest(
                    kind=INSTRUCTOR,
                    professor_name=full_name,
                    comments=select_comments(
                        comments, limit=max_comments, max_chars=comment_chars
                    ),
                    term_labels=labels,
                ),
            )
        )

    if not include_courses:
        return jobs, thin

    by_course: dict[int, list[CommentInput]] = {}
    for comment in comments:
        code = normalize_code(comment.class_code)
        course_id = course_ids.get(code) if code else None
        if course_id is None:
            continue
        by_course.setdefault(course_id, []).append(comment)

    for course_id, course_comments in by_course.items():
        if len(course_comments) < min_comments:
            thin += 1
            continue
        if (INSTRUCTOR_COURSE, course_id) in existing:
            continue
        code = next((c for c, cid in course_ids.items() if cid == course_id), None)
        jobs.append(
            Job(
                instructor_id=instructor_id,
                subject_type=INSTRUCTOR_COURSE,
                course_id=course_id,
                window=window,
                request=SummaryRequest(
                    kind=INSTRUCTOR_COURSE,
                    professor_name=full_name,
                    course_code=code or str(course_id),
                    comments=select_comments(
                        course_comments, limit=max_comments, max_chars=comment_chars
                    ),
                    term_labels=labels,
                ),
            )
        )
    return jobs, thin


async def _store(session: AsyncSession, job: Job, result: SummaryResult) -> None:
    window_start, window_end = job.window or (None, None)
    await session.execute(
        _SUMMARY_UPSERT,
        {
            "subject_type": job.subject_type,
            "instructor_id": job.instructor_id,
            "course_id": job.course_id,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "window_start": window_start,
            "window_end": window_end,
            "summary_md": result.summary_md,
            "facets": result.facets,
            "source_rating_count": result.source_comment_count,
            "generated_at": datetime.now(tz=None).astimezone(),
        },
    )


def make_summarizer(*, stub: bool, model: str | None = None) -> Summarizer:
    settings = get_settings()
    if stub or not settings.gemini_api_key:
        if not stub:
            log.warning("GEMINI_API_KEY is unset -- falling back to the stub summarizer")
        return StubSummarizer()
    return GeminiSummarizer(
        api_key=settings.gemini_api_key,
        model=model or settings.gemini_model,
        bucket=TokenBucket(settings.summary_rpm),
    )


async def run(
    *,
    limit: int,
    dry_run: bool,
    stub: bool,
    min_comments: int,
    terms_back: int,
    include_courses: bool,
    model: str | None,
) -> Stats:
    settings = get_settings()
    stats = Stats()

    async with session_scope() as session:
        course_ids = {
            str(row[1]): int(row[0]) for row in (await session.execute(_COURSE_CODES)).all()
        }
        candidates = (await session.execute(_CANDIDATES, {"limit": limit})).mappings().all()
        log.info("%d professors with ratings; %d known course codes", len(candidates), len(course_ids))

        all_jobs: list[Job] = []
        for candidate in candidates:
            stats.professors += 1
            rows = [
                dict(row)
                for row in (
                    await session.execute(_COMMENTS, {"rmp_id": candidate["rmp_id"]})
                )
                .mappings()
                .all()
            ]
            existing = {
                (row[0], int(row[1]) if row[1] is not None else None)
                for row in (
                    await session.execute(
                        _EXISTING,
                        {
                            "instructor_id": candidate["instructor_id"],
                            "prompt_version": PROMPT_VERSION,
                        },
                    )
                ).all()
            }
            jobs, thin = build_jobs(
                instructor_id=int(candidate["instructor_id"]),
                full_name=candidate["full_name"],
                rows=rows,
                course_ids=course_ids,
                existing=existing,
                min_comments=min_comments,
                terms_back=terms_back,
                max_comments=settings.summary_max_comments,
                comment_chars=settings.summary_comment_chars,
                include_courses=include_courses,
            )
            stats.skipped_thin += thin
            stats.skipped_existing += len(existing)
            all_jobs.extend(jobs)

        log.info("%d summaries to generate", len(all_jobs))

        if dry_run:
            for job in all_jobs:
                prompt = build_prompt(job.request)
                stats.prompt_tokens += estimate_tokens(prompt)
                subject = job.request.course_code or "instructor-level"
                log.info(
                    "--- %s / %s (%d comments, ~%d tokens)",
                    job.request.professor_name,
                    subject,
                    len(job.request.comments),
                    estimate_tokens(prompt),
                )
                log.debug("%s", prompt)
            log.info("DRY RUN %s (no API calls, nothing written)", stats.report())
            return stats

        summarizer = make_summarizer(stub=stub, model=model)
        if isinstance(summarizer, GeminiSummarizer):
            await summarizer.verify_model()
            log.info("using model %s at %d rpm", summarizer.model, settings.summary_rpm)

        for job in all_jobs:
            try:
                result = await summarizer.summarize(job.request)
            except Exception as exc:  # noqa: BLE001 - one failure must not lose the rest
                stats.failed += 1
                log.warning(
                    "summary failed for instructor %s (%s): %s",
                    job.instructor_id,
                    job.request.course_code or "instructor",
                    exc,
                )
                continue
            await _store(session, job, result)
            if job.subject_type == INSTRUCTOR:
                stats.instructor_summaries += 1
            else:
                stats.course_summaries += 1
            if (stats.instructor_summaries + stats.course_summaries) % 10 == 0:
                await session.commit()
                log.info("progress %s", stats.report())

        await session.commit()
        if stats.instructor_summaries or stats.course_summaries:
            version = await bump_data_version(session)
            log.info("data_version now %d (hot cache invalidated)", version)

    log.info("done %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="professors to consider")
    parser.add_argument(
        "--dry-run", action="store_true", help="print prompts and token estimates only"
    )
    parser.add_argument("--stub", action="store_true", help="use the stub summarizer")
    parser.add_argument("--min-comments", type=int, default=3)
    parser.add_argument("--terms-back", type=int, default=2, help="semesters to include")
    parser.add_argument(
        "--no-courses", action="store_true", help="instructor-level summaries only"
    )
    parser.add_argument("--model", default=None, help="override GEMINI_MODEL")
    parser.add_argument("-v", "--verbose", action="store_true", help="also log full prompts")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(
        run(
            limit=args.limit,
            dry_run=args.dry_run,
            stub=args.stub,
            min_comments=args.min_comments,
            terms_back=args.terms_back,
            include_courses=not args.no_courses,
            model=args.model,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
