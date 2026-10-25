"""Professor lookup -- the read path the hot cache exists for."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import presenters, repository
from app.cache import CACHE_STATE, CacheRegistry, get_caches
from app.config import Settings, get_settings
from app.db import get_session
from app.freshness import ensure_fresh
from app.schemas import ProfessorOut, SearchOut, SummaryEnvelopeOut, SummaryOut
from app.scoring import ScoreWeights
from app.services.summarize import PROMPT_VERSION

router = APIRouter(prefix="/professors", tags=["professors"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CachesDep = Annotated[CacheRegistry, Depends(get_caches)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def cache_state() -> str:
    """HIT, MISS, JOIN, or BYPASS for the lookup this request just did."""
    return CACHE_STATE.get() or "BYPASS"


def stamp(response: Response) -> None:
    """Expose whether this response came from the cache.

    Set in the endpoint rather than in middleware on purpose: Starlette runs
    BaseHTTPMiddleware in its own task, so a ContextVar written inside the
    endpoint is not visible up there.
    """
    response.headers["X-Cache"] = cache_state()


def not_found(instructor_id: int) -> HTTPException:
    """404 carrying the cache header, which an exception response would drop.

    It matters here: a missing id is negatively cached, and the header is how
    you can see that the second 404 cost nothing.
    """
    return HTTPException(
        status_code=404,
        detail=f"no instructor {instructor_id}",
        headers={"X-Cache": cache_state()},
    )


async def load_professor_payload(
    session: AsyncSession,
    caches: CacheRegistry,
    settings: Settings,
    instructor_id: int,
) -> dict[str, Any] | None:
    """Cached professor detail. ``None`` means no such professor (cached briefly)."""
    await ensure_fresh(session, caches)
    weights = ScoreWeights.from_settings(settings)

    async def factory() -> dict[str, Any] | None:
        raw = await repository.load_professor(
            session, instructor_id, prompt_version=PROMPT_VERSION
        )
        return presenters.professor_payload(raw, weights) if raw else None

    return await caches.professors.get_or_compute(caches.key("prof", instructor_id), factory)


@router.get("/search", response_model=SearchOut)
async def search_professors(
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
    q: str = Query("", max_length=120, description="Name fragment; empty lists everyone."),
    dept: str | None = Query(None, max_length=120),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    await ensure_fresh(session, caches)
    weights = ScoreWeights.from_settings(settings)
    filters = {"q": q.strip().lower(), "dept": dept, "limit": limit, "offset": offset}
    key = caches.key("search", caches.digest(filters))

    async def factory() -> dict[str, Any]:
        payload = await repository.search_instructors(
            session, query=q, department=dept, limit=limit, offset=offset
        )
        payload["results"] = [presenters.search_hit(row, weights) for row in payload["results"]]
        return payload

    payload = await caches.search.get_or_compute(key, factory)
    stamp(response)
    return payload


@router.get("/{instructor_id}", response_model=ProfessorOut)
async def get_professor(
    instructor_id: int,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    payload = await load_professor_payload(session, caches, settings, instructor_id)
    stamp(response)
    if payload is None:
        raise not_found(instructor_id)
    await caches.recents.record(instructor_id, payload["full_name"])
    return payload


@router.get("/{instructor_id}/courses", response_model=list[dict])
async def get_professor_courses(
    instructor_id: int,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
) -> list[dict[str, Any]]:
    """Courses this professor has taught, best first. Served from the same cached payload."""
    payload = await load_professor_payload(session, caches, settings, instructor_id)
    stamp(response)
    if payload is None:
        raise not_found(instructor_id)
    return payload["courses"]


@router.get("/{instructor_id}/summary", response_model=SummaryEnvelopeOut)
async def get_professor_summary(
    instructor_id: int,
    response: Response,
    session: SessionDep,
    caches: CachesDep,
    settings: SettingsDep,
    course: str | None = Query(
        None,
        max_length=20,
        description="Course code like CSCE121 for the class-specific summary; "
        "omit for the instructor-level one.",
    ),
) -> dict[str, Any]:
    """Read a stored summary.

    Never calls Gemini: free-tier limits make an in-request LLM call a bad bet,
    so ``status: "missing"`` is a normal answer until the batch job has run.
    """
    payload = await load_professor_payload(session, caches, settings, instructor_id)
    stamp(response)
    if payload is None:
        raise not_found(instructor_id)

    wanted_code = course.strip().upper().replace(" ", "") if course else None
    match: dict[str, Any] | None = None
    for summary in payload["summaries"]:
        if wanted_code is None and summary.get("subject_type") == "instructor":
            match = summary
            break
        if wanted_code is not None and summary.get("course_code") == wanted_code:
            match = summary
            break

    return {
        "status": "ready" if match else "missing",
        "instructor_id": instructor_id,
        "course_code": wanted_code,
        "prompt_version": PROMPT_VERSION,
        "summary": SummaryOut.model_validate(match) if match else None,
    }
