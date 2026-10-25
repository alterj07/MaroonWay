"""Per-student storage: what they asked for, and what they kept.

Identity comes from the Next.js server, which is the only part of the system
that has verified a Google session. It sends the student's Google subject with
a shared secret; this service trusts the header only when that secret matches,
and never sees a password or a token from Google.

Worth being explicit, because it is easy to assume otherwise: a Google sign-in
proves someone holds a tamu.edu account. It is **not** a Howdy login -- Howdy
authenticates a NetID through CAS with Duo two-factor -- so nothing here can
read a student's registration, schedule or grades.
"""

from __future__ import annotations

import json

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import (
    SavedScheduleOut,
    SaveScheduleRequest,
    StudentOut,
    StudentPreferencesOut,
    StudentPreferencesRequest,
)

router = APIRouter(prefix="/me", tags=["me"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_student(
    session: SessionDep,
    settings: SettingsDep,
    x_internal_token: Annotated[str | None, Header()] = None,
    x_student_subject: Annotated[str | None, Header()] = None,
    x_student_email: Annotated[str | None, Header()] = None,
    x_student_name: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Resolve the signed-in student, creating the row on first sight."""
    if not settings.internal_token:
        raise HTTPException(status_code=503, detail="INTERNAL_TOKEN is not configured")
    if x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="bad internal token")
    if not x_student_subject or not x_student_email:
        raise HTTPException(status_code=401, detail="no student identity")
    if not x_student_email.lower().endswith("@tamu.edu"):
        # The frontend restricts the Google domain; this is the second line.
        raise HTTPException(status_code=403, detail="a tamu.edu account is required")

    row = (
        await session.execute(
            text(
                """
                insert into students (subject, email, name)
                values (cast(:subject as text), cast(:email as text), cast(:name as text))
                on conflict (subject) do update
                    set email = excluded.email,
                        name = coalesce(excluded.name, students.name),
                        last_seen_at = now()
                returning id, subject, email, name
                """
            ),
            {
                "subject": x_student_subject,
                "email": x_student_email.lower(),
                "name": x_student_name,
            },
        )
    ).mappings().one()
    await session.commit()
    return dict(row)


StudentDep = Annotated[dict, Depends(current_student)]


@router.get("", response_model=StudentOut)
async def who_am_i(student: StudentDep) -> dict[str, Any]:
    return student


@router.get("/preferences", response_model=StudentPreferencesOut)
async def read_preferences(student: StudentDep, session: SessionDep) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                select wants, weights, engine, updated_at
                from student_preferences
                where student_id = cast(:id as bigint)
                """
            ),
            {"id": student["id"]},
        )
    ).mappings().first()
    return dict(row) if row else {"wants": None, "weights": {}, "engine": None}


@router.put("/preferences", response_model=StudentPreferencesOut)
async def write_preferences(
    request: StudentPreferencesRequest,
    student: StudentDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Remember what a student asked for, so they do not retype it."""
    row = (
        await session.execute(
            text(
                """
                insert into student_preferences (student_id, wants, weights, engine, updated_at)
                values (cast(:id as bigint), cast(:wants as text),
                        cast(:weights as jsonb), cast(:engine as text), now())
                on conflict (student_id) do update
                    set wants = excluded.wants,
                        weights = excluded.weights,
                        engine = excluded.engine,
                        updated_at = now()
                returning wants, weights, engine, updated_at
                """
            ),
            {
                "id": student["id"],
                "wants": request.wants,
                "weights": json.dumps(request.weights),
                "engine": request.engine,
            },
        )
    ).mappings().one()
    await session.commit()
    return dict(row)


@router.get("/schedules", response_model=list[SavedScheduleOut])
async def list_schedules(student: StudentDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                select id, term, label, payload, created_at
                from saved_schedules
                where student_id = cast(:id as bigint)
                order by created_at desc
                limit 50
                """
            ),
            {"id": student["id"]},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/schedules", response_model=SavedScheduleOut)
async def save_schedule(
    request: SaveScheduleRequest,
    student: StudentDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Keep a schedule as it was served, so it still renders later.

    The payload is stored rather than a list of section ids on purpose: a
    saved schedule should not change or break when the term's sections are
    reloaded.
    """
    row = (
        await session.execute(
            text(
                """
                insert into saved_schedules (student_id, term, label, payload)
                values (cast(:id as bigint), cast(:term as text),
                        cast(:label as text), cast(:payload as jsonb))
                returning id, term, label, payload, created_at
                """
            ),
            {
                "id": student["id"],
                "term": request.term,
                "label": request.label,
                "payload": json.dumps(request.payload),
            },
        )
    ).mappings().one()
    await session.commit()
    return dict(row)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    student: StudentDep,
    session: SessionDep,
) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            delete from saved_schedules
            where id = cast(:schedule_id as bigint)
              and student_id = cast(:student_id as bigint)
            """
        ),
        {"schedule_id": schedule_id, "student_id": student["id"]},
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such saved schedule")
    return {"deleted": schedule_id}
