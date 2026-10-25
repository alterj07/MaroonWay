"""Schedule building.

The planning doc's REQUIRED rule lives here: at least 20 minutes between
classes, which the student may raise. Candidate sections come from the database
with their instructor's scores already attached, and ranking is the doc's --
RMP score first, then difficulty.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.cache import CacheRegistry, get_caches
from app.config import Settings, get_settings
from app.db import get_session
from app.freshness import ensure_fresh
from app.ingest.run_traits import QUESTION_VERSION
from app.routers.professors import stamp
from app.schemas import (
    PreferenceRequest,
    PreferenceResponse,
    ScheduleRequest,
    ScheduleResponse,
)
from app.services import preferences as prefs_service
from app.services import scheduling
from app.services.jev import build_decider
from app.services.preferences import PREFERENCE_QUESTIONS, Preferences, Traits

router = APIRouter(prefix="/schedule", tags=["schedule"])

#: Where "early morning" stops, in minutes since midnight.
#:
#: A&M's first slot is 08:00 and the next common ones are 08:35 and 09:10, so a
#: student who says "nothing early" means they will take the 09:10 but not the
#: 08:00.
EARLY_MORNING_ENDS = 9 * 60

#: How many structurally-valid schedules to rank over before trimming to the
#: caller's limit. Generation prunes as it goes, so this is cheap.
SCHEDULE_POOL = 400

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CachesDep = Annotated[CacheRegistry, Depends(get_caches)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def to_section(row: dict[str, Any]) -> scheduling.Section:
    return scheduling.Section(
        section_id=int(row["section_id"]),
        course_id=int(row["course_id"]),
        code=row["code"],
        section_code=row["section_code"],
        term=row["term"],
        instructor_id=row.get("instructor_id"),
        instructor_name=row.get("instructor_name"),
        campus=row.get("campus"),
        delivery=row.get("delivery"),
        honors=bool(row.get("honors")),
        seats_open=row.get("seats_open"),
        meetings=scheduling.parse_meetings(row.get("meets")),
        adj_rating=None if row.get("adj_rating") is None else float(row["adj_rating"]),
        adj_difficulty=(
            None if row.get("adj_difficulty") is None else float(row["adj_difficulty"])
        ),
        adj_gpa=None if row.get("adj_gpa") is None else float(row["adj_gpa"]),
        pct_a=None if row.get("pct_a") is None else float(row["pct_a"]),
    )


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def decider_for(settings: Settings):
    return build_decider(settings)


def preferences_payload(preferences: Preferences) -> dict[str, Any]:
    return {
        "rating": preferences.rating,
        "difficulty": preferences.difficulty,
        "grades": preferences.grades,
        "workload": preferences.workload,
        "lecture": preferences.lecture,
        "attendance": preferences.attendance,
        "avoid_early_mornings": preferences.avoid_early_mornings,
        "avoid_fridays": preferences.avoid_fridays,
        "delivery": preferences.delivery,
        "campus": preferences.campus,
        "honors": preferences.honors,
        "min_gap_minutes": preferences.min_gap_minutes,
        "engine": preferences.engine,
        "low_confidence": list(preferences.low_confidence),
        "stated": preferences.stated,
    }


def to_payload(ranked: prefs_service.RankedSchedule) -> dict[str, Any]:
    schedule = ranked.schedule
    return {
        "preference_score": round(ranked.preference_score, 4),
        "reasons": list(ranked.reasons),
        "contributions": [
            {
                "name": c.name,
                "weight": round(c.weight, 4),
                "value": round(c.value, 4),
                "points": round(c.points, 4),
            }
            for c in ranked.contributions
        ],
        "sections": [
            {
                "section_id": s.section_id,
                "course_id": s.course_id,
                "code": s.code,
                "section_code": s.section_code,
                "instructor_id": s.instructor_id,
                "instructor_name": s.instructor_name,
                "campus": s.campus,
                "delivery": s.delivery,
                "honors": s.honors,
                "seats_open": s.seats_open,
                "meetings": [
                    {
                        "day": m.day,
                        "start": scheduling.format_time(m.start),
                        "end": scheduling.format_time(m.end),
                        "building": m.building,
                        "room": m.room,
                    }
                    for m in s.meetings
                ],
                "adj_rating": s.adj_rating,
                "adj_difficulty": s.adj_difficulty,
                "adj_gpa": s.adj_gpa,
                "pct_a": s.pct_a,
            }
            for s in schedule.sections
        ],
        "tightest_gap": schedule.tightest_gap,
        "mean_rating": schedule.mean_rating,
        "mean_difficulty": schedule.mean_difficulty,
        "mean_gpa": schedule.mean_gpa,
        "mean_pct_a": schedule.mean_pct_a,
        "earliest_start": (
            None
            if schedule.earliest_start is None
            else scheduling.format_time(schedule.earliest_start)
        ),
        "days_on_campus": schedule.days_on_campus,
        "idle_minutes": schedule.idle_minutes,
    }


@router.get("/terms")
async def list_terms(session: SessionDep) -> list[dict[str, Any]]:
    """Which terms have sections loaded, and how many carry meeting times.

    Worth checking first: a term whose sections have no times cannot be
    scheduled, and this says so instead of returning an empty schedule list.
    """
    return await repository.available_terms(session)


@router.get("/courses")
async def list_courses(
    session: SessionDep,
    term: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Courses with sections this term, most choice first."""
    return await repository.courses_with_sections(session, term=term, limit=limit)


@router.post("/preferences", response_model=PreferenceResponse)
async def read_preferences(
    request: PreferenceRequest,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Turn what a student said into typed weights, without building anything.

    Lets the UI show what was understood -- and how confidently -- before any
    schedule is generated. One Jev call: twelve questions, one pass.
    """
    decisions = await decider_for(settings).decide(request.wants, PREFERENCE_QUESTIONS)
    resolved = Preferences.from_decisions(decisions, stated=request.wants)
    return {
        "preferences": preferences_payload(resolved),
        "answers": {
            name: {
                "kind": answer.kind,
                "value": answer.value,
                "confidence": answer.confidence,
                "unit": round(answer.unit(), 4),
            }
            for name, answer in decisions.answers.items()
        },
    }


@router.post("", response_model=ScheduleResponse)
async def generate_schedules(
    request: ScheduleRequest,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Build conflict-free schedules, ranked by what the student asked for.

    When ``wants`` is given, Jev turns it into weights and those drive the
    ranking; the doc's rule (RMP score, then difficulty) stays the tiebreak.
    With no ``wants``, the doc's rule decides outright.

    Cached on the whole request, because a student tweaking one filter re-asks
    almost the same question repeatedly.
    """
    await ensure_fresh(session, caches)
    key = caches.key("schedule", caches.digest(request.model_dump()))

    async def factory() -> dict[str, Any]:
        # 1. What does the student want?
        if request.wants:
            decisions = await decider_for(settings).decide(request.wants, PREFERENCE_QUESTIONS)
            preferences = Preferences.from_decisions(decisions, stated=request.wants)
        else:
            preferences = Preferences()

        # An explicit gap always beats an inferred one.
        min_gap = (
            request.min_gap_minutes
            if request.min_gap_minutes is not None
            else preferences.min_gap_minutes
        )
        # Only filters the student set explicitly exclude sections. What Jev
        # inferred from their words is a ranking signal instead, so an
        # inferred "prefers in person" cannot silently return nothing.

        # 2. Which sections could they take?
        rows = await repository.sections_for_courses(
            session,
            term=request.term,
            codes=request.courses,
            campus=request.campus,
            honors=request.honors,
            delivery=request.delivery,
            open_only=request.open_only,
        )
        candidates: dict[str, list[scheduling.Section]] = {
            code.upper(): [] for code in request.courses
        }
        for row in rows:
            candidates.setdefault(row["code"], []).append(to_section(row))

        request_availability = scheduling.Availability(
            earliest=scheduling.parse_time(request.earliest),
            latest=scheduling.parse_time(request.latest),
            excluded_days=frozenset(
                day for value in request.excluded_days for day in scheduling.parse_days(value)
            ),
        )
        # Generate a wide pool, then let preferences choose from it. This has to
        # be generous: generate() orders by the doc's rule and truncates, so a
        # small pool is already biased toward high ratings -- and a student who
        # asked for no Friday classes would never see the Friday-free options,
        # because they rank lower on rating before preferences are applied.
        availability = request_availability
        pool_size = max(request.limit * 4, SCHEDULE_POOL)

        # Preferences stated clearly enough to be worth obeying rather than
        # merely scoring. Scoring alone was not enough: with a hundred sections
        # to a course the pool fills with the highest-rated combinations long
        # before a Friday-free or late-starting one appears, so the preference
        # was understood and then silently did nothing.
        #
        # They are applied together, in one search. Applying them one at a time
        # meant a search per constraint plus an unconstrained one that was
        # always discarded -- three passes over a combination space that takes
        # seconds to walk, which is why a four-course build took the better
        # part of a minute. Relaxing only happens when the constrained search
        # comes back empty, which is rare and is the case that can afford it.
        constraints: list[tuple[str, scheduling.Availability]] = []
        wanted = availability
        if (
            preferences.avoid_fridays > prefs_service.CLEAR_SIGNAL
            and "FRI" not in availability.excluded_days
        ):
            wanted = replace(
                wanted, excluded_days=wanted.excluded_days | frozenset({"FRI"})
            )
            constraints.append(("no Friday classes", wanted))
        if (
            preferences.avoid_early_mornings > prefs_service.CLEAR_SIGNAL
            and availability.earliest is None
        ):
            wanted = replace(wanted, earliest=EARLY_MORNING_ENDS)
            constraints.append(("no early mornings", wanted))

        relaxed: list[str] = []
        schedules = scheduling.generate(
            candidates, min_gap=min_gap, availability=wanted, limit=pool_size
        )
        availability = wanted

        # Nothing fits with everything asked for: drop the constraints one at a
        # time, most recently added first, and say which could not be met.
        while not schedules and constraints:
            label, _ = constraints.pop()
            relaxed.append(f"{label} was impossible for these courses")
            fallback = constraints[-1][1] if constraints else request_availability
            schedules = scheduling.generate(
                candidates, min_gap=min_gap, availability=fallback, limit=pool_size
            )
            availability = fallback

        # 3. What did Jev read about these professors?
        instructor_ids = sorted(
            {s.instructor_id for pool in candidates.values() for s in pool if s.instructor_id}
        )
        traits: dict[int, Traits] = {}
        for row in await repository.traits_for_instructors(
            session, instructor_ids, version=QUESTION_VERSION
        ):
            # The professor-level row is the general one; a course-level row
            # refines it, so it wins where present.
            instructor_id = int(row["instructor_id"])
            if row["course_id"] is None and instructor_id in traits:
                continue
            traits[instructor_id] = Traits(
                lots_of_quizzes=_number(row["lots_of_quizzes"]),
                exam_difficulty=_number(row["exam_difficulty"]),
                lecture_quality=_number(row["lecture_quality"]),
                attendance_taken=_number(row["attendance_taken"]),
                extra_credit=_number(row["extra_credit"]),
                heavy_workload=_number(row["heavy_workload"]),
                grades_generously=_number(row["grades_generously"]),
                engine=row["model"],
                review_count=int(row["review_count"] or 0),
            )

        # 4. Rank.
        ranked = prefs_service.rank(schedules, preferences, traits)[: request.limit]
        detail = (
            None
            if ranked
            else scheduling.describe_failure(
                candidates, min_gap=min_gap, availability=availability
            )
        )
        resolved = replace(preferences, min_gap_minutes=min_gap)
        return {
            "request": request.model_dump(),
            "count": len(ranked),
            "schedules": [to_payload(r) for r in ranked],
            "preferences": preferences_payload(resolved),
            "detail": detail,
            "relaxed": relaxed,
        }

    payload = await caches.search.get_or_compute(key, factory)
    stamp(response)
    return payload
