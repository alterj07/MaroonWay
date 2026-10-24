"""The HTTP surface, with the database faked out.

These exercise what the routers actually add on top of SQL: caching, the X-Cache
header, 404s, the recently-viewed log, and the summary envelope. The SQL itself
is checked by tests/test_integration_db.py, which needs a real Postgres.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import repository
from app.config import Settings, get_settings
from app.db import get_session

PROFESSOR_ROW = {
    "instructor_id": 7,
    "full_name": "Jane Doe",
    "department": "Computer Science",
    "rmp_id": 200147,
    "rating_count": 12,
    "raw_rating": Decimal("4.50"),
    "raw_difficulty": Decimal("3.20"),
    "would_take_again_percent": Decimal("83.00"),
    "adj_rating": Decimal("4.0455"),
    "adj_difficulty": Decimal("3.1000"),
    "adj_would_take_again": Decimal("3.7045"),
    "adj_gpa": Decimal("3.9000"),
    "courses": [
        {
            "course_id": 3,
            "code": "CSCE121",
            "title": "Intro to Program Design",
            "campus": "CSTAT",
            "honors": False,
            "class_rating_count": 4,
            "section_count": 2,
            "adj_rating": Decimal("4.2"),
            "adj_difficulty": Decimal("3.4"),
            "adj_would_take_again": None,
            "adj_gpa": Decimal("3.1"),
        }
    ],
    "grades": [],
    "recent_comments": [],
    "summaries": [
        {
            "subject_type": "instructor",
            "course_id": None,
            "course_code": None,
            "model": "gemini-flash-lite-latest",
            "prompt_version": "v1",
            "summary_md": "Clear lecturer.",
            "facets": {"confidence": "medium"},
            "window_start": None,
            "window_end": None,
            "source_rating_count": 9,
            "generated_at": None,
        },
        {
            "subject_type": "instructor_course",
            "course_id": 3,
            "course_code": "CSCE121",
            "model": "gemini-flash-lite-latest",
            "prompt_version": "v1",
            "summary_md": "Hard tests, fair grading.",
            "facets": {"attendance": "mandatory"},
            "window_start": None,
            "window_end": None,
            "source_rating_count": 4,
            "generated_at": None,
        },
    ],
}

SEARCH_ROW = {
    **{k: v for k, v in PROFESSOR_ROW.items() if not isinstance(v, list)},
    "name_similarity": Decimal("0.9"),
}

COURSE_ROW = {
    "instructor_id": 7,
    "full_name": "Jane Doe",
    "department": "Computer Science",
    "rmp_id": 200147,
    "class_rating_count": 4,
    "instructor_rating_count": 12,
    "section_count": 2,
    "adj_rating": Decimal("4.2"),
    "adj_difficulty": Decimal("3.4"),
    "adj_would_take_again": None,
    "adj_gpa": Decimal("3.1"),
}


class FakeRepo:
    """Records how often the "expensive" reads actually happen."""

    def __init__(self) -> None:
        self.professor_calls: list[int] = []
        self.search_calls: list[dict] = []
        self.course_calls: list[dict] = []

    async def load_professor(self, session, instructor_id, *, prompt_version, **kwargs):
        self.professor_calls.append(instructor_id)
        return PROFESSOR_ROW if instructor_id == 7 else None

    async def search_instructors(self, session, *, query="", department=None, limit=20, offset=0):
        self.search_calls.append({"query": query, "limit": limit})
        return {
            "query": query,
            "department": department,
            "total": 1,
            "limit": limit,
            "offset": offset,
            "results": [SEARCH_ROW],
        }

    async def course_instructors(self, session, *, dept, number, limit=50):
        self.course_calls.append({"dept": dept, "number": number})
        return [COURSE_ROW]

    async def current_data_version(self, session):
        return 0

    async def popular_instructor_ids(self, session, limit):
        return []


@pytest.fixture
def repo(monkeypatch) -> FakeRepo:
    fake = FakeRepo()
    for name in (
        "load_professor",
        "search_instructors",
        "course_instructors",
        "current_data_version",
        "popular_instructor_ids",
    ):
        monkeypatch.setattr(repository, name, getattr(fake, name))
    return fake


@pytest.fixture
def api_settings() -> Settings:
    return Settings(
        # Port 1 refuses instantly: nothing here should reach a database.
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        cache_negative_ttl=30.0,
        admin_token=None,
    )


@pytest.fixture
def client(repo, api_settings, monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: api_settings)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: api_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_professor_detail_is_served_then_cached(client, repo):
    first = client.get("/professors/7")
    second = client.get("/professors/7")

    assert first.status_code == second.status_code == 200
    assert first.headers["x-cache"] == "MISS"
    assert second.headers["x-cache"] == "HIT"
    assert repo.professor_calls == [7], "the second view must not touch Postgres"

    body = first.json()
    assert body["full_name"] == "Jane Doe"
    assert body["score"]["adj_rating"] == pytest.approx(4.0455)
    assert body["score"]["composite"] != 0
    assert body["courses"][0]["code"] == "CSCE121"


def test_unknown_professor_is_404_and_remembered_as_missing(client, repo):
    first = client.get("/professors/999")
    second = client.get("/professors/999")

    assert first.status_code == second.status_code == 404
    assert second.headers["x-cache"] == "HIT"
    assert repo.professor_calls == [999], "a hammered bad id must not re-query"


def test_viewing_a_professor_records_it_as_recently_viewed(client):
    client.get("/professors/7")
    stats = client.get("/cache/stats").json()

    assert stats["recently_viewed"][0]["instructor_id"] == 7
    assert stats["recently_viewed"][0]["name"] == "Jane Doe"
    professors = next(c for c in stats["caches"] if c["name"] == "professors")
    assert professors["size"] == 1
    assert professors["misses"] == 1


def test_cache_stats_report_hits_after_a_repeat_view(client):
    client.get("/professors/7")
    client.get("/professors/7")
    professors = next(
        c for c in client.get("/cache/stats").json()["caches"] if c["name"] == "professors"
    )

    assert professors["hits"] == 1
    assert professors["hit_rate"] == 0.5


def test_search_is_cached_per_filter_set(client, repo):
    client.get("/professors/search", params={"q": "doe"})
    client.get("/professors/search", params={"q": "doe"})
    assert len(repo.search_calls) == 1

    client.get("/professors/search", params={"q": "doe", "limit": 5})
    assert len(repo.search_calls) == 2, "different filters are a different key"


def test_search_results_are_shaped_for_the_frontend(client):
    body = client.get("/professors/search", params={"q": "doe"}).json()
    hit = body["results"][0]

    assert body["total"] == 1
    assert hit["full_name"] == "Jane Doe"
    assert hit["score"]["rating_count"] == 12
    assert hit["name_similarity"] == pytest.approx(0.9)


def test_search_rejects_a_silly_limit(client):
    assert client.get("/professors/search", params={"limit": 500}).status_code == 422


def test_professor_courses_reuse_the_cached_payload(client, repo):
    client.get("/professors/7")
    response = client.get("/professors/7/courses")

    assert response.status_code == 200
    assert response.headers["x-cache"] == "HIT"
    assert response.json()[0]["code"] == "CSCE121"
    assert repo.professor_calls == [7]


def test_instructor_level_summary_is_the_default(client):
    body = client.get("/professors/7/summary").json()
    assert body["status"] == "ready"
    assert body["summary"]["subject_type"] == "instructor"
    assert body["summary"]["summary_md"] == "Clear lecturer."
    assert body["course_code"] is None


def test_a_course_summary_is_selected_by_code(client):
    body = client.get("/professors/7/summary", params={"course": "csce 121"}).json()
    assert body["status"] == "ready"
    assert body["summary"]["course_code"] == "CSCE121"
    assert body["summary"]["facets"]["attendance"] == "mandatory"


def test_a_summary_that_has_not_been_generated_is_missing_not_an_error(client):
    body = client.get("/professors/7/summary", params={"course": "MATH151"}).json()
    assert body["status"] == "missing"
    assert body["summary"] is None
    assert body["prompt_version"] == "v1"


def test_summary_for_an_unknown_professor_is_404(client):
    assert client.get("/professors/999/summary").status_code == 404


def test_course_instructors_are_ranked_and_cached(client, repo):
    response = client.get("/courses/CSCE/121/instructors")
    client.get("/courses/CSCE/121/instructors")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["full_name"] == "Jane Doe"
    assert row["class_rating_count"] == 4
    assert isinstance(row["composite"], float)
    assert len(repo.course_calls) == 1


def test_healthz_reports_degraded_when_postgres_is_unreachable(client):
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    assert body["detail"]


def test_cache_invalidation_needs_a_configured_token(client):
    assert client.post("/admin/cache/invalidate").status_code == 503


def test_cache_invalidation_checks_the_token(repo, monkeypatch):
    configured = Settings(
        database_url="postgresql+asyncpg://user:pw@127.0.0.1:1/none",
        cache_warm_count=0,
        admin_token="let-me-in",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: configured)
    app = main_module.app

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        with TestClient(app) as client:
            client.get("/professors/7")
            assert client.post("/admin/cache/invalidate").status_code == 401
            assert (
                client.post(
                    "/admin/cache/invalidate", headers={"x-admin-token": "wrong"}
                ).status_code
                == 401
            )
            cleared = client.post(
                "/admin/cache/invalidate", headers={"x-admin-token": "let-me-in"}
            )
            assert cleared.status_code == 200
            assert cleared.json()["cleared"]["professors"] == 1
    finally:
        app.dependency_overrides.clear()


def test_openapi_lists_the_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/professors/search" in paths
    assert "/professors/{instructor_id}" in paths
    assert "/professors/{instructor_id}/summary" in paths
    assert "/courses/{dept}/{number}/instructors" in paths
    assert "/cache/stats" in paths
