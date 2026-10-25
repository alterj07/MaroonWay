"""POST /sections/import -- sections scraped from a logged-in browser.

A&M's class search is behind NetID plus Duo, so there is no server-side scrape.
This endpoint takes what the student's own browser can already see. The tests
here cover the normalising, because the payload shape is whatever a page
yielded and the whole point is to be forgiving about that without being loose
about what gets stored.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings, get_settings
from app.db import get_session
from app.ingest import load_sections
from app.routers import sections as sections_router

TOKEN = "import-me"


@pytest.fixture
def written(monkeypatch) -> list:
    """Capture what would be persisted, without a database."""
    captured: list = []

    async def fake_persist(records, *, stats=None):
        captured.extend(records)
        result = stats or load_sections.Stats()
        result.sections_loaded = len(records)
        result.meetings = sum(len(r.meetings) for r in records)
        return result

    monkeypatch.setattr(sections_router, "persist", fake_persist)
    return captured


@pytest.fixture
def client(monkeypatch, written):
    settings = Settings(
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        import_token=TOKEN,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def section(**overrides) -> dict:
    base = {
        "term": "FALL 2026",
        "subject": "CSCE",
        "number": "121",
        "section": "501",
        "instructor": "DOE J",
        "campus": "College Station",
        "delivery": "Face to Face",
        "seats": 60,
        "seats_open": 4,
        "meetings": [
            {"days": "MWF", "start": "09:10", "end": "10:00", "building": "ZACH", "room": "350"}
        ],
    }
    return {**base, **overrides}


def post(client, sections, *, token=TOKEN, dry_run=False):
    headers = {"x-import-token": token} if token else {}
    return client.post(
        "/sections/import", json={"sections": sections, "dry_run": dry_run}, headers=headers
    )


def test_a_token_is_required(client):
    assert post(client, [section()], token=None).status_code == 401
    assert post(client, [section()], token="wrong").status_code == 401


def test_a_good_import_writes_and_reports(client, written):
    body = post(client, [section()]).json()

    assert body["received"] == 1
    assert body["accepted"] == 1
    assert body["sections_written"] == 1
    assert body["meetings"] == 3, "MWF expands to three meetings"
    assert len(written) == 1
    assert written[0].dept == "CSCE"
    assert written[0].campus == "CSTAT"
    assert written[0].delivery == "F2F"


def test_a_dry_run_writes_nothing(client, written):
    body = post(client, [section()], dry_run=True).json()

    assert body["dry_run"] is True
    assert body["sections_written"] == 0
    assert body["meetings"] == 3, "still reports what it found"
    assert written == [], "nothing persisted"


def test_a_combined_course_code_is_accepted(client, written):
    post(client, [section(subject=None, number=None, course="MATH 151")])
    assert (written[0].dept, written[0].number) == ("MATH", "151")


def test_two_meeting_patterns_land_on_one_section(client, written):
    """A lecture plus a lab is two rows on the page but one registration."""
    lecture = section()
    lab = section(
        meetings=[{"days": "T", "start": "14:00", "end": "15:50", "building": "ZACH", "room": "105"}]
    )
    body = post(client, [lecture, lab]).json()

    assert body["accepted"] == 1
    assert body["meetings"] == 4
    assert len(written) == 1
    assert {m["day"] for m in written[0].meetings} == {"MON", "WED", "FRI", "TUE"}


def test_a_row_with_no_course_code_is_counted_not_dropped_silently(client):
    body = post(client, [section(subject=None, number=None, course=None)]).json()
    assert body["accepted"] == 0
    assert body["skipped"]["no_course_code"] == 1


def test_an_online_section_with_no_times_is_kept(client, written):
    body = post(client, [section(delivery="Web Based", meetings=[])]).json()
    assert body["accepted"] == 1
    assert written[0].delivery == "WEB"
    assert written[0].meetings == []


def test_a_timeless_in_person_section_is_kept_but_flagged(client, written):
    """No invented time: it is stored without meetings and counted, because a
    section the scheduler cannot place should be visible as such."""
    body = post(client, [section(meetings=[])]).json()
    assert body["accepted"] == 1
    assert body["skipped"]["no_meeting_time"] == 1
    assert written[0].meetings == []


def test_an_unparseable_time_does_not_become_a_meeting(client, written):
    post(client, [section(meetings=[{"days": "MWF", "start": "by appt", "end": None}])])
    assert written[0].meetings == []


def test_a_backwards_time_is_rejected(client, written):
    post(client, [section(meetings=[{"days": "MON", "start": "15:00", "end": "09:00"}])])
    assert written[0].meetings == []


def test_twelve_hour_clock_times_are_understood(client, written):
    post(client, [section(meetings=[{"days": "TR", "start": "1:25 PM", "end": "2:40 PM"}])])
    starts = {m["start"] for m in written[0].meetings}
    assert starts == {"13:25"}


def test_unknown_fields_from_the_page_are_ignored(client):
    assert post(client, [{**section(), "whatever_the_page_had": "noise"}]).status_code == 200


def test_an_empty_import_is_rejected(client):
    assert post(client, []).status_code == 422


def test_the_endpoint_refuses_when_no_token_is_configured(monkeypatch):
    settings = Settings(
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        import_token=None,
        admin_token=None,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            assert post(client, [section()]).status_code == 503
    finally:
        app.dependency_overrides.clear()
