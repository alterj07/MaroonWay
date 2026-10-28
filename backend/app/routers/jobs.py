"""Jobs a scheduler triggers.

Generating the summaries is a long, rate-limited batch
(``app/ingest/run_summaries.py``), so it cannot happen inside a request:
Postgres pings this route, a bounded chunk starts in the background, and the
response comes back at once. The chunk is small on purpose -- the job skips
rows it has already written, so repeated small runs converge on a finished
dataset without any one request outliving the proxy carrying it.

Overlapping pings are refused rather than queued. Two concurrent runs would
select the same candidates and spend the Gemini quota twice on work only one of
them stores.

The schedule itself lives in ``sql/004_summaries_cron.sql``, so what runs and
when is in the repository rather than in dashboard state nobody can find later.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.schemas import SummaryRunOut, SummaryRunRequest

log = logging.getLogger("maroonway.jobs")

router = APIRouter(prefix="/admin/summaries", tags=["admin"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

#: render.yaml pins the service to one worker, so in-process state is the whole
#: picture. A second worker would each keep its own copy of this and the
#: refusal below would stop refusing; that belongs in Postgres if it ever
#: happens.
_state: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "last_error": None,
}

#: A task nothing holds a reference to can be garbage collected mid-run.
_task: asyncio.Task[None] | None = None


def require_admin(settings: Settings, token: str | None) -> None:
    """The same guard as ``POST /admin/cache/invalidate``."""
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured")
    if token != settings.admin_token:
        raise HTTPException(status_code=401, detail="bad admin token")


async def _run_chunk(payload: SummaryRunRequest) -> None:
    """One bounded pass of the batch, recording how it went either way."""
    # Imported here so the ingest module and its dependencies stay off the web
    # service's import path until something actually asks for a run.
    from app.ingest.run_summaries import run

    try:
        stats = await run(
            limit=payload.limit,
            dry_run=False,
            stub=False,
            min_comments=payload.min_comments,
            terms_back=payload.terms_back,
            include_courses=payload.include_courses,
            model=None,
        )
    except Exception as exc:  # noqa: BLE001 - recorded for /status, not swallowed silently
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        log.exception("summary chunk failed")
    else:
        _state["last_error"] = None
        _state["last_report"] = stats.report()
        log.info("summary chunk done: %s", stats.report())
    finally:
        _state["state"] = "idle"
        _state["finished_at"] = datetime.now(tz=timezone.utc)


@router.post("/run", response_model=SummaryRunOut, status_code=202)
async def start_run(
    settings: SettingsDep,
    payload: SummaryRunRequest | None = None,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Start a chunk and return immediately.

    202, not 200: the work has been accepted, not done. The caller is a cron
    job that fires and forgets, so a response it has to wait for would only
    report a timeout on a job that was running perfectly well.
    """
    require_admin(settings, x_admin_token)
    if _state["state"] == "running":
        raise HTTPException(status_code=409, detail="a summary run is already in progress")

    # Set before the first await: the event loop cannot interleave a second
    # request between the check above and these lines, so two pings arriving
    # together cannot both pass.
    _state["state"] = "running"
    _state["started_at"] = datetime.now(tz=timezone.utc)
    _state["finished_at"] = None

    global _task
    _task = asyncio.create_task(_run_chunk(payload or SummaryRunRequest()))
    return dict(_state)


@router.get("/status", response_model=SummaryRunOut)
async def run_status(
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """What the last chunk did -- the thing pg_net's own log cannot tell you."""
    require_admin(settings, x_admin_token)
    return dict(_state)
