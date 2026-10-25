"""Health and cache observability."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text

from app import repository
from app.cache import CacheRegistry, get_caches
from app.config import Settings, get_settings
from app.schemas import HealthOut

router = APIRouter(tags=["meta"])

CachesDep = Annotated[CacheRegistry, Depends(get_caches)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/healthz", response_model=HealthOut)
async def healthz(request: Request, caches: CachesDep) -> dict[str, Any]:
    """Ping the database and report the data version the cache is keyed on.

    Deliberately tolerant: the app boots and answers here even when Postgres is
    unreachable, so "is the service up" and "is the database up" stay separable.
    """
    factory = request.app.state.session_factory
    try:
        async with factory() as session:
            await session.execute(text("select 1"))
            version = await repository.current_data_version(session)
            await caches.set_data_version(version)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {
            "status": "degraded",
            "database": "unreachable",
            "data_version": caches.data_version,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {"status": "ok", "database": "ok", "data_version": version}


@router.get("/cache/stats")
async def cache_stats(caches: CachesDep) -> dict[str, Any]:
    """Per-cache counters plus the professors people just opened."""
    return await caches.stats_payload()


@router.post("/admin/cache/invalidate")
async def invalidate_cache(
    caches: CachesDep,
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured")
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="bad admin token")
    return {"cleared": await caches.invalidate_all()}
