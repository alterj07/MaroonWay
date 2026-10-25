"""Schedule building.

The planning doc's REQUIRED rule lives here: at least 20 minutes between
classes, which the student may raise. Candidate sections come from the database
with their instructor's scores already attached, and ranking is the doc's --
RMP score first, then difficulty.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.cache import CacheRegistry, get_caches
from app.config import Settings, get_settings
from app.db import get_session
from app.freshness import ensure_fresh
from app.routers.professors import stamp
from app.schemas import ScheduleRequest, ScheduleResponse
from app.services import scheduling

router = APIRouter(prefix="/schedule", tags=["schedule"])

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
    )


def to_payload(schedule: scheduling.Schedule) -> dict[str, Any]:
    return {
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
            }
            for s in schedule.sections
        ],
        "tightest_gap": schedule.tightest_gap,
        "mean_rating": schedule.mean_rating,
        "mean_difficulty": schedule.mean_difficulty,
        "mean_gpa": schedule.mean_gpa,
        "earliest_start": (
            None
            if schedule.earliest_start is None
            else scheduling.format_time(schedule.earliest_start)
        ),
        "days_on_campus": schedule.days_on_campus,
    }


@router.get("/terms")
async def list_terms(session: SessionDep) -> list[dict[str, Any]]:
    """Which terms have sections loaded, and how many carry meeting times.

    Worth checking first: a term whose sections have no times cannot be
    scheduled, and this says so instead of returning an empty schedule list.
    """
    return await repository.available_terms(session)


@router.post("", response_model=ScheduleResponse)
async def generate_schedules(
    request: ScheduleRequest,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Build conflict-free schedules, best first.

    Cached on the whole request, because the same student tweaking one filter
    re-asks the same question repeatedly.
    """
    await ensure_fresh(session, caches)
    key = caches.key("schedule", caches.digest(request.model_dump()))

    async def factory() -> dict[str, Any]:
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

        availability = scheduling.Availability(
            earliest=scheduling.parse_time(request.earliest),
            latest=scheduling.parse_time(request.latest),
            excluded_days=frozenset(
                day for value in request.excluded_days for day in scheduling.parse_days(value)
            ),
        )
        schedules = scheduling.generate(
            candidates,
            min_gap=request.min_gap_minutes,
            availability=availability,
            limit=request.limit,
        )
        detail = (
            None
            if schedules
            else scheduling.describe_failure(
                candidates, min_gap=request.min_gap_minutes, availability=availability
            )
        )
        return {
            "request": request.model_dump(),
            "count": len(schedules),
            "schedules": [to_payload(s) for s in schedules],
            "detail": detail,
        }

    payload = await caches.search.get_or_compute(key, factory)
    stamp(response)
    return payload
