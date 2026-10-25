"""Course-first lookup: given a class, who should I take it from?"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import presenters, repository
from app.cache import CacheRegistry, get_caches
from app.config import Settings, get_settings
from app.db import get_session
from app.freshness import ensure_fresh
from app.routers.professors import stamp
from app.schemas import CourseInstructorOut
from app.scoring import ScoreWeights

router = APIRouter(prefix="/courses", tags=["courses"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CachesDep = Annotated[CacheRegistry, Depends(get_caches)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/explore")
async def explore(
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    q: str = Query("", max_length=120, description="Course code, title or professor name"),
    limit: int = Query(60, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Courses for the explorer, each carrying its professors.

    The professors travel with the course because that is what the card shows:
    a student comparing CSCE 121 sections is really comparing instructors.
    """
    await ensure_fresh(session, caches)
    key = caches.key("explore", caches.digest({"q": q.strip().lower(), "limit": limit}))

    async def factory() -> list[dict[str, Any]]:
        return await repository.explore_courses(session, query=q, limit=limit)

    payload = await caches.search.get_or_compute(key, factory)
    stamp(response)
    return payload


@router.get("/{dept}/{number}/instructors", response_model=list[CourseInstructorOut])
async def course_instructors(
    dept: str,
    number: str,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Everyone who has taught the course, ranked RMP score first then difficulty.

    Scores are class-specific where that professor has reviews mentioning this
    class, and fall back to their overall score where they do not.
    """
    await ensure_fresh(session, caches)
    weights = ScoreWeights.from_settings(settings)
    key = caches.key("course", dept.upper(), number, limit)

    async def factory() -> list[dict[str, Any]]:
        rows = await repository.course_instructors(
            session, dept=dept, number=number, limit=limit
        )
        return [presenters.course_instructor(row, weights) for row in rows]

    payload = await caches.search.get_or_compute(key, factory)
    stamp(response)
    return payload
