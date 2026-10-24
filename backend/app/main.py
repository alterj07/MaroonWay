"""The FastAPI app.

No CORS middleware, on purpose: the Next.js frontend fetches this service from
its *server* (Server Components), so the backend URL and any keys never reach a
browser and no preflight is involved. If you ever point a client component
straight at this service, that is the moment to add CORS -- and to decide
whether this API should be public at all.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app import repository
from app.cache import CacheRegistry, warm_professor_cache
from app.config import get_settings
from app.db import make_engine, make_session_factory
from app.presenters import professor_payload
from app.routers import courses, meta, professors
from app.scoring import ScoreWeights
from app.services.summarize import PROMPT_VERSION

log = logging.getLogger("maroonway")


def configure_logging(level: int = logging.INFO) -> None:
    """Make our own log lines visible under uvicorn.

    uvicorn configures handlers for its own loggers only, so without this the
    root logger has none and everything below WARNING is swallowed -- including
    "warmed N professors", which is how you tell the cache is doing its job.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
            datefmt="%H:%M:%S",
        )
    log.setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    engine = make_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    data_version = 0
    try:
        async with app.state.session_factory() as session:
            data_version = await repository.current_data_version(session)
    except Exception as exc:  # noqa: BLE001 - /healthz reports this
        log.warning("could not read data_version at boot: %s", exc)

    app.state.caches = CacheRegistry(settings, data_version=data_version)

    # Pre-load the most-rated professors so the first click of a demo is a HIT.
    if settings.cache_warm_count > 0:
        try:
            weights = ScoreWeights.from_settings(settings)
            async with app.state.session_factory() as session:
                async def loader(instructor_id: int):
                    raw = await repository.load_professor(
                        session, instructor_id, prompt_version=PROMPT_VERSION
                    )
                    return professor_payload(raw, weights) if raw else None

                ids = await repository.popular_instructor_ids(
                    session, settings.cache_warm_count
                )
                warmed = await warm_professor_cache(app.state.caches, loader, ids)
            log.info("warmed %d professors into the hot cache", warmed)
        except Exception as exc:  # noqa: BLE001 - a cold cache is not fatal
            log.warning("cache warm-up skipped: %s", exc)

    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="MaroonWay API",
    version="0.1.0",
    summary="Professor ratings, grade history, and AI comment summaries for A&M schedules.",
    lifespan=lifespan,
)

app.include_router(meta.router)
app.include_router(professors.router)
app.include_router(courses.router)
