"""Accepting sections scraped from a logged-in browser.

A&M closed its public course API in 2023, and the replacement sits behind NetID
plus Duo two-factor. There is no server-side scrape that can get past that, and
asking a student for their NetID password would be both a terms violation and a
bad idea.

What does work: the student is already logged in. A userscript running in their
own browser reads the Class Search results they can already see and posts them
here. No credential ever leaves their machine, the second factor is already
satisfied, and this service never holds anything it should not.

The payload is deliberately forgiving -- whatever shape the page yields gets
normalised here, through the same code path as a CSV export, so one importer
serves both.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.ingest.load_sections import ParsedRow, persist
from app.schemas import SectionImportRequest, SectionImportResponse
from app.services.scheduling import format_time, parse_days, parse_time

log = logging.getLogger("maroonway.import")

router = APIRouter(prefix="/sections", tags=["sections"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

COURSE_SPLIT = ("subject", "number")


def _course(section: Any) -> tuple[str, str] | None:
    if section.subject and section.number:
        return section.subject.strip().upper(), section.number.strip().upper()
    from app.ingest.columns import split_course_code

    return split_course_code(section.course)


def to_parsed(section: Any) -> tuple[ParsedRow | None, str]:
    """One posted section to the loader's own record type."""
    course = _course(section)
    if course is None:
        return None, "no_course_code"
    dept, number = course
    if not section.term or not section.section:
        return None, "no_term_or_section"

    meetings: list[dict[str, Any]] = []
    for meeting in section.meetings:
        start = parse_time(meeting.start)
        end = parse_time(meeting.end)
        if start is None or end is None or end <= start:
            continue
        for day in parse_days(meeting.days):
            meetings.append(
                {
                    "day": day,
                    "start": format_time(start),
                    "end": format_time(end),
                    "building": meeting.building,
                    "room": meeting.room,
                }
            )

    from app.ingest.load_sections import normalize_delivery
    from app.ingest.load_grades import normalize_campus

    delivery = normalize_delivery(section.delivery)
    return (
        ParsedRow(
            term=section.term.strip(),
            dept=dept,
            number=number,
            section_code=str(section.section).strip(),
            instructor=section.instructor,
            campus=normalize_campus(section.campus),
            delivery=delivery or ("WEB" if not meetings else "F2F"),
            honors=bool(section.honors),
            seats=section.seats,
            seats_open=section.seats_open,
            meetings=meetings,
        ),
        "" if meetings or delivery == "WEB" else "no_meeting_time",
    )


@router.post("/import", response_model=SectionImportResponse)
async def import_sections(
    request: SectionImportRequest,
    settings: SettingsDep,
    x_import_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Take sections a browser scraped and load them.

    Token-guarded: this writes to the sections table, which the whole scheduler
    reads. ``dry_run`` reports what would happen and writes nothing, which is
    how to check a userscript's selectors before trusting them.
    """
    expected = settings.import_token or settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=503, detail="IMPORT_TOKEN (or ADMIN_TOKEN) is not configured"
        )
    if x_import_token != expected:
        raise HTTPException(status_code=401, detail="bad import token")

    grouped: dict[tuple[str, str, str, str], ParsedRow] = {}
    skipped: dict[str, int] = {}
    for section in request.sections:
        record, reason = to_parsed(section)
        if record is None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        key = (record.term, record.dept, record.number, record.section_code)
        if key in grouped:
            grouped[key].meetings.extend(record.meetings)
        else:
            grouped[key] = record

    meetings = sum(len(r.meetings) for r in grouped.values())
    if request.dry_run:
        log.info("dry run: %d sections, %d meetings", len(grouped), meetings)
        return {
            "received": len(request.sections),
            "accepted": len(grouped),
            "sections_written": 0,
            "meetings": meetings,
            "skipped": skipped,
            "unknown_courses": [],
            "unknown_instructors": [],
            "dry_run": True,
        }

    result = await persist(list(grouped.values()))
    log.info(
        "imported %d sections (%d meetings) from a browser session",
        result.sections_loaded,
        meetings,
    )
    return {
        "received": len(request.sections),
        "accepted": len(grouped),
        "sections_written": result.sections_loaded,
        "meetings": meetings,
        "skipped": {**skipped, **result.skip_reasons},
        "unknown_courses": sorted(result.unknown_courses)[:50],
        "unknown_instructors": sorted(result.unknown_instructors)[:50],
        "dry_run": False,
    }
