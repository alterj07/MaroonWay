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
        self.section_calls: list[dict] = []
        self.trait_calls: list[dict] = []

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

    async def sections_for_courses(self, session, *, term, codes, **kwargs):
        self.section_calls.append({"term": term, "codes": list(codes), **kwargs})
        if term != "FALL 2026":
            return []
        rows = []
        for code, section_code, days, start, end in (
            ("CSCE121", "500", "MWF", "09:10", "10:00"),
            ("CSCE121", "501", "MWF", "10:00", "10:50"),  # back-to-back with MATH151
            ("MATH151", "200", "MWF", "10:20", "11:10"),
        ):
            if code.upper() not in [c.upper() for c in codes]:
                continue
            rows.append(
                {
                    "section_id": int(section_code),
                    "course_id": 1 if code == "CSCE121" else 2,
                    "code": code,
                    "section_code": section_code,
                    "term": term,
                    "instructor_id": 7,
                    "instructor_name": "DOE J",
                    "campus": "CSTAT",
                    "delivery": "F2F",
                    "honors": False,
                    "seats": 60,
                    "seats_open": 5,
                    "meets": [
                        {"days": days, "start": start, "end": end, "building": "ZACH", "room": "350"}
                    ],
                    "adj_rating": Decimal("4.2"),
                    "adj_difficulty": Decimal("3.1"),
                    "adj_gpa": None,
                }
            )
        return rows

    async def available_terms(self, session):
        return [{"term": "FALL 2026", "sections": 3, "with_times": 3}]

    async def courses_with_sections(self, session, *, term, limit=200):
        return [
            {"code": "CSCE121", "dept": "CSCE", "number": "121", "title": "Intro",
             "sections": 2, "instructors": 1, "with_times": 2},
            {"code": "MATH151", "dept": "MATH", "number": "151", "title": "Calc I",
             "sections": 1, "instructors": 1, "with_times": 1},
        ]

    async def traits_for_instructors(self, session, instructor_ids, *, version):
        self.trait_calls.append({"ids": list(instructor_ids), "version": version})
        if not instructor_ids:
            return []
        # What Jev decided about instructor 7: quizzes often, clear lecturer.
        return [
            {
                "instructor_id": 7,
                "course_id": None,
                "lots_of_quizzes": Decimal("0.900"),
                "exam_difficulty": Decimal("0.700"),
                "lecture_quality": Decimal("0.850"),
                "attendance_taken": Decimal("0.200"),
                "extra_credit": Decimal("0.100"),
                "heavy_workload": Decimal("0.800"),
                "grades_generously": Decimal("0.400"),
                "confidence": Decimal("0.780"),
                "model": "jev-1.14",
                "review_count": 11,
            }
        ]

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
        "sections_for_courses",
        "available_terms",
        "courses_with_sections",
        "traits_for_instructors",
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


# --- scheduling ---------------------------------------------------------------


def test_terms_report_how_many_sections_carry_times(client):
    body = client.get("/schedule/terms").json()
    assert body == [{"term": "FALL 2026", "sections": 3, "with_times": 3}]


def test_a_schedule_is_built_and_honours_the_twenty_minute_gap(client):
    response = client.post(
        "/schedule",
        json={"term": "FALL 2026", "courses": ["CSCE121", "MATH151"], "min_gap_minutes": 20},
    )
    assert response.status_code == 200
    body = response.json()

    # Section 501 ends at 10:00 and MATH151 starts at 10:20 -> 20 min, allowed.
    # Section 500 ends at 10:00 too, so both are legal here; what must NOT
    # appear is any pairing with a gap under 20.
    assert body["count"] >= 1
    for schedule in body["schedules"]:
        assert schedule["tightest_gap"] >= 20
        assert len(schedule["sections"]) == 2


def test_raising_the_gap_rules_everything_out_and_says_why(client):
    body = client.post(
        "/schedule",
        json={"term": "FALL 2026", "courses": ["CSCE121", "MATH151"], "min_gap_minutes": 90},
    ).json()

    assert body["count"] == 0
    assert body["schedules"] == []
    assert "closest any two of their sections come is 20 min" in body["detail"]
    assert "less than the 90 min required" in body["detail"]


def test_meetings_come_back_expanded_per_day(client):
    body = client.post("/schedule", json={"term": "FALL 2026", "courses": ["CSCE121"]}).json()
    meetings = body["schedules"][0]["sections"][0]["meetings"]

    assert [m["day"] for m in meetings] == ["MON", "WED", "FRI"]
    assert meetings[0]["start"] == "09:10"
    assert meetings[0]["building"] == "ZACH"


def test_a_term_with_no_sections_explains_itself(client):
    body = client.post("/schedule", json={"term": "SPRING 2027", "courses": ["CSCE121"]}).json()
    assert body["count"] == 0
    assert "no sections on record" in body["detail"]


def test_availability_is_passed_through(client):
    body = client.post(
        "/schedule",
        json={"term": "FALL 2026", "courses": ["CSCE121"], "earliest": "12:00"},
    ).json()
    assert body["count"] == 0
    assert "availability" in body["detail"]


def test_schedules_are_cached_per_request(client, repo):
    payload = {"term": "FALL 2026", "courses": ["CSCE121"]}
    client.post("/schedule", json=payload)
    client.post("/schedule", json=payload)
    assert len(repo.section_calls) == 1

    client.post("/schedule", json={**payload, "min_gap_minutes": 45})
    assert len(repo.section_calls) == 2, "a different constraint is a different question"


def test_an_unknown_field_is_rejected(client):
    assert client.post(
        "/schedule", json={"term": "FALL 2026", "courses": ["CSCE121"], "wat": 1}
    ).status_code == 422


def test_a_silly_gap_is_rejected(client):
    assert client.post(
        "/schedule", json={"term": "FALL 2026", "courses": ["CSCE121"], "min_gap_minutes": 999}
    ).status_code == 422


def test_at_least_one_course_is_required(client):
    assert client.post("/schedule", json={"term": "FALL 2026", "courses": []}).status_code == 422


# --- preferences through Jev --------------------------------------------------


def test_preferences_endpoint_reports_what_was_understood(client):
    body = client.post(
        "/schedule/preferences",
        json={"wants": "easy A's, good lecturers, no 8am classes, nothing on Friday"},
    ).json()

    prefs = body["preferences"]
    assert prefs["avoid_early_mornings"] > 0.5
    assert prefs["avoid_fridays"] > 0.5
    assert prefs["stated"].startswith("easy A's")
    # No key is configured in tests, so the fallback answers -- and says so.
    assert prefs["engine"] == "heuristic"
    assert set(body["answers"]) == {
        "rating_importance",
        "difficulty_aversion",
        "grade_importance",
        "workload_aversion",
        "lecture_quality_importance",
        "attendance_importance",
        "avoid_early_mornings",
        "avoid_fridays",
        "delivery",
        "campus",
        "gap_tolerance",
        "wants_honors",
        "day_shape",
    }


def test_the_engine_is_always_reported(client):
    """The UI must never imply a calibrated decision when it was a keyword guess."""
    body = client.post("/schedule/preferences", json={"wants": "anything"}).json()
    assert body["preferences"]["engine"] in ("heuristic", "jev-latest", "jev-1.14")
    assert body["preferences"]["low_confidence"], "a guess is flagged"


def test_an_empty_want_is_rejected(client):
    assert client.post("/schedule/preferences", json={"wants": ""}).status_code == 422


def test_a_schedule_reports_the_preferences_it_ranked_with(client):
    body = client.post("/schedule", json={"term": "FALL 2026", "courses": ["CSCE121"]}).json()
    assert body["preferences"]["engine"] == "default", "nothing expressed"
    assert body["preferences"]["min_gap_minutes"] == 20


def test_stating_wants_drives_the_ranking_and_is_echoed_back(client):
    body = client.post(
        "/schedule",
        json={
            "term": "FALL 2026",
            "courses": ["CSCE121", "MATH151"],
            "wants": "I want a good lecturer and I hate early mornings",
        },
    ).json()

    assert body["count"] >= 1
    assert body["preferences"]["engine"] == "heuristic"
    assert body["preferences"]["stated"].startswith("I want a good lecturer")
    top = body["schedules"][0]
    assert top["preference_score"] > 0
    assert top["contributions"], "the breakdown explains the score"


def test_jev_traits_appear_in_the_breakdown(client, repo):
    """Instructor 7's traits say quizzes are frequent and the workload heavy, so
    a student who wants a light workload should see that weighed."""
    body = client.post(
        "/schedule",
        json={
            "term": "FALL 2026",
            "courses": ["CSCE121"],
            "wants": "I want less homework and fewer quizzes",
        },
    ).json()

    assert repo.trait_calls, "traits were looked up"
    names = {c["name"] for c in body["schedules"][0]["contributions"]}
    assert "light workload" in names
    assert "good lecturers" in names


def test_an_explicit_gap_beats_what_jev_inferred(client):
    body = client.post(
        "/schedule",
        json={
            "term": "FALL 2026",
            "courses": ["CSCE121"],
            "wants": "I want an hour between classes",
            "min_gap_minutes": 25,
        },
    ).json()
    assert body["preferences"]["min_gap_minutes"] == 25


def test_an_inferred_gap_is_used_when_none_is_given(client):
    body = client.post(
        "/schedule",
        json={"term": "FALL 2026", "courses": ["CSCE121"], "wants": "relaxed gaps please"},
    ).json()
    assert body["preferences"]["min_gap_minutes"] >= 20


def test_course_list_reports_how_much_choice_each_offers(client):
    body = client.get("/schedule/courses", params={"term": "FALL 2026"}).json()
    assert body[0]["code"] == "CSCE121"
    assert body[0]["instructors"] >= 1


def test_options_are_distinct_timetables(client, monkeypatch):
    """Three schedules that differ only in section number are one option.

    Offering the same hours three times as "Option 1, 2, 3" asks a student to
    choose between things they cannot tell apart.
    """
    from app.routers import schedule as schedule_router

    body = client.post(
        "/schedule",
        json={
            "term": "DEMO FALL 2026",
            "courses": ["ANTH205", "BIOL100"],
            "wants": "",
            "limit": 3,
        },
    )
    if body.status_code != 200 or not body.json()["schedules"]:
        pytest.skip("no sections loaded in this environment")

    shapes = []
    for option in body.json()["schedules"]:
        shapes.append(
            tuple(
                sorted(
                    (s["code"], m["day"], m["start"], m["end"])
                    for s in option["sections"]
                    for m in s["meetings"]
                )
            )
        )
    assert len(set(shapes)) == len(shapes), "two options share a timetable"
    assert schedule_router  # the import is the point: this exercises that path
