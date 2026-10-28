"""The scheduled-summary trigger.

What matters here is the guard rails rather than the batch itself: a wrong
token must not start anything, a second ping must not start a second run, and a
run that fails must say so afterwards instead of leaving the route wedged at
"running" forever.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings, get_settings
from app.db import get_session
from app.routers import jobs

TOKEN = "test-admin-token"


@pytest.fixture(autouse=True)
def idle_state():
    """Each test starts from a clean module-level state and leaves one."""
    jobs._state.update(
        state="idle", started_at=None, finished_at=None, last_report=None, last_error=None
    )
    yield
    jobs._state.update(state="idle")


@pytest.fixture
def job_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        admin_token=TOKEN,
    )


@pytest.fixture
def client(job_settings, monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: job_settings)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: job_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def chunks(monkeypatch) -> list[dict]:
    """Record what the background task was asked for, without running a batch."""
    calls: list[dict] = []

    async def fake_chunk(payload):
        calls.append(payload.model_dump())
        jobs._state["state"] = "idle"

    monkeypatch.setattr(jobs, "_run_chunk", fake_chunk)
    return calls


def test_run_starts_a_chunk_and_returns_at_once(client, chunks):
    response = client.post("/admin/summaries/run", headers={"X-Admin-Token": TOKEN})

    assert response.status_code == 202, "accepted, not finished"
    assert response.json()["state"] == "running"
    assert chunks == [
        {"limit": 25, "min_comments": 3, "terms_back": 2, "include_courses": True}
    ]


def test_body_overrides_the_chunk_size(client, chunks):
    client.post(
        "/admin/summaries/run", headers={"X-Admin-Token": TOKEN}, json={"limit": 5}
    )

    assert chunks[0]["limit"] == 5


def test_a_bad_token_starts_nothing(client, chunks):
    response = client.post("/admin/summaries/run", headers={"X-Admin-Token": "wrong"})

    assert response.status_code == 401
    assert chunks == [], "an unauthorised ping must not reach the batch"


def test_a_missing_token_starts_nothing(client, chunks):
    assert client.post("/admin/summaries/run").status_code == 401
    assert chunks == []


def test_overlapping_pings_are_refused(client, chunks):
    jobs._state["state"] = "running"

    response = client.post("/admin/summaries/run", headers={"X-Admin-Token": TOKEN})

    assert response.status_code == 409, "two runs would spend the quota twice"
    assert chunks == []


def test_status_reports_the_previous_run(client, chunks):
    jobs._state["last_report"] = "professors=25 instructor=4 course=6"

    response = client.get("/admin/summaries/status", headers={"X-Admin-Token": TOKEN})

    assert response.status_code == 200
    assert response.json()["last_report"] == "professors=25 instructor=4 course=6"
    assert response.json()["state"] == "idle"


def test_status_needs_the_token(client):
    assert client.get("/admin/summaries/status").status_code == 401


def test_without_an_admin_token_the_route_is_unavailable(monkeypatch):
    """503, not 401: nothing is misconfigured on the caller's end."""
    unconfigured = Settings(
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        admin_token=None,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: unconfigured)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: unconfigured
    try:
        with TestClient(app) as client:
            assert client.post("/admin/summaries/run").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_a_failed_chunk_releases_the_guard(monkeypatch):
    """A crashed run must not leave every later ping answering 409."""

    async def exploding_run(**_kwargs):
        raise RuntimeError("Gemini said no")

    monkeypatch.setattr("app.ingest.run_summaries.run", exploding_run)
    jobs._state["state"] = "running"

    from app.schemas import SummaryRunRequest

    asyncio.run(jobs._run_chunk(SummaryRunRequest()))

    assert jobs._state["state"] == "idle"
    assert "Gemini said no" in jobs._state["last_error"]
    assert jobs._state["finished_at"] is not None
