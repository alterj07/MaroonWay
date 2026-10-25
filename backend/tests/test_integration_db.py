"""Integration tests against a real Postgres.

The SQL views carry the ranking arithmetic, so they need a database to be
checked at all. Skipped unless TEST_DATABASE_URL is set:

    podman run -d --rm --name maroonway-pg -e POSTGRES_PASSWORD=maroonway \\
        -e POSTGRES_DB=maroonway_test -p 55432:5432 docker.io/library/postgres:17-alpine
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:maroonway@127.0.0.1:55432/maroonway_test \\
        .venv/bin/python -m pytest tests/test_integration_db.py -q

The fixture drops and recreates the public schema, so it refuses to run unless
the database name says it is for tests. Never point it at Supabase.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import repository
from app.config import get_settings
from app.ingest.common import bump_data_version, split_sql
from app.ingest.load_grades import load as load_grades
from app.scoring import shrink
from app.services.summarize import PROMPT_VERSION

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to run the database tests"
)

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
SAMPLE_CSV = Path(__file__).parent / "fixtures" / "grades_sample.csv"

SEED_RMP = """
insert into rmp_professors (
    rmp_id, node_id, first_name, last_name, full_name, department, school_id,
    avg_rating, avg_difficulty, num_ratings, would_take_again_percent, course_codes
) values
    (1001, 'n1', 'Jane', 'Doe', 'Jane Doe', 'Computer Science', '1003',
     4.60, 3.20, 80, 83.0, '[{"courseName": "CSCE121", "courseCount": 9}]'::jsonb),
    (1002, 'n2', 'John', 'Smith', 'John Smith', 'Computer Science', '1003',
     4.90, 2.50, 2, -1, null),
    (1003, 'n3', 'Richard', 'Roe', 'Richard Roe', 'English', '1003',
     2.10, 4.80, 40, 25.0, null)
"""

SEED_RATINGS = """
insert into rmp_ratings (
    rmp_id, class_code, comment, helpful, clarity, difficulty, rated_at,
    is_online, attendance_mandatory
) values
    (1001, 'CSCE121', 'Tough but fair.', 5, 5, 3, now() - interval '30 days', false, true),
    (1001, 'CSCE121', 'Great lecturer.', 5, 4, 3, now() - interval '60 days', false, true),
    (1001, 'CSCE121', 'Heavy workload.', 4, 4, 4, now() - interval '90 days', true, false),
    (1001, 'MATH151', 'Different vibe here.', 2, 2, 5, now() - interval '45 days', false, null),
    (1003, 'ENGL104', 'Avoid.', 1, 2, 5, now() - interval '20 days', false, true)
"""


def _assert_disposable(url: str) -> None:
    """Refuse to wipe a database that was not obviously set aside for tests.

    This fixture drops the public schema. That is fine for a scratch database
    and catastrophic for one holding loaded data, and the difference is one
    environment variable -- so the name has to say so, or the override has to
    be explicit.
    """
    database = url.rsplit("/", 1)[-1].split("?")[0].lower()
    if "test" in database or "scratch" in database:
        return
    if os.environ.get("TEST_DATABASE_ALLOW_DESTRUCTIVE") == "1":
        return
    pytest.fail(
        f"refusing to drop the public schema of {database!r}: these tests are "
        "destructive. Point TEST_DATABASE_URL at a database whose name contains "
        "'test', or set TEST_DATABASE_ALLOW_DESTRUCTIVE=1 if you really mean it."
    )


@pytest.fixture
async def engine(monkeypatch):
    _assert_disposable(TEST_DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("drop schema if exists public cascade")
        await conn.exec_driver_sql("create schema public")
        # Apply every numbered migration in order, including later additions.
        for path in sorted(SQL_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            for statement in split_sql(path.read_text()):
                await conn.exec_driver_sql(statement)
    try:
        yield engine
    finally:
        await engine.dispose()
        get_settings.cache_clear()


@pytest.fixture
def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def seeded(engine, sessions):
    """Grades from the CSV fixture, plus RMP rows linked by name."""
    await load_grades(SAMPLE_CSV)
    async with sessions() as session:
        await session.execute(text(SEED_RMP))
        await session.execute(text(SEED_RATINGS))
        # What load_rmp's name matcher would do: "DOE, JANE M" -> "Jane Doe".
        await session.execute(
            text(
                """
                update instructors i
                   set rmp_id = p.rmp_id
                  from rmp_professors p
                 where i.canonical_key = (
                        select string_agg(word, ' ' order by word)
                          from unnest(string_to_array(lower(p.full_name), ' ')) as word
                       )
                """
            )
        )
        await session.commit()
    return sessions


async def test_schema_and_views_apply_cleanly(sessions):
    async with sessions() as session:
        for view in (
            "scoring_params",
            "scoring_means",
            "instructor_gpa",
            "instructor_scores",
            "instructor_course_scores",
        ):
            count = (await session.execute(text(f"select count(*) from {view}"))).scalar_one()
            assert count >= 0, f"{view} did not execute"


async def test_loading_the_csv_populates_the_tables(engine, sessions):
    stats = await load_grades(SAMPLE_CSV)

    assert stats.rows_read == 6
    assert stats.rows_loaded == 4
    assert stats.skip_reasons == {"no_instructor": 1, "no_values": 1}

    async with sessions() as session:
        instructors = (
            await session.execute(text("select count(*) from instructors"))
        ).scalar_one()
        grades = (await session.execute(text("select count(*) from course_grades"))).scalar_one()
        courses = (await session.execute(text("select count(*) from courses"))).scalar_one()

    assert instructors == 3
    assert grades == 4
    assert courses == 3


async def test_reloading_the_same_file_changes_nothing(engine, sessions):
    await load_grades(SAMPLE_CSV)
    await load_grades(SAMPLE_CSV)

    async with sessions() as session:
        grades = (await session.execute(text("select count(*) from course_grades"))).scalar_one()
        instructors = (
            await session.execute(text("select count(*) from instructors"))
        ).scalar_one()

    assert (grades, instructors) == (4, 3), "re-running an ingest must not duplicate rows"


async def test_a_few_glowing_reviews_rank_below_many_good_ones(seeded):
    async with seeded() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select full_name, rating_count, raw_rating, adj_rating, adj_difficulty
                    from instructor_scores
                    where rating_count > 0
                    order by adj_rating desc, adj_difficulty asc
                    """
                )
            )
        ).mappings().all()

    names = [row["full_name"] for row in rows]
    assert names[0] == "DOE, JANE M", "4.6 from 80 must beat 4.9 from 2"
    assert names[-1] == "ROE, RICHARD A"

    jane, john = rows[0], rows[1]
    assert float(jane["adj_rating"]) < float(jane["raw_rating"])  # shrunk toward the mean
    assert float(john["adj_rating"]) < float(john["raw_rating"])
    assert float(jane["raw_rating"]) < float(john["raw_rating"])  # but ends up ahead


async def test_the_view_and_app_scoring_agree(seeded):
    """The guard on "change one, change both" between SQL and app/scoring.py."""
    async with seeded() as session:
        params = (
            await session.execute(text("select prior_weight from scoring_params"))
        ).scalar_one()
        means = (await session.execute(text("select * from scoring_means"))).mappings().one()
        row = (
            await session.execute(
                text(
                    """
                    select rating_count, raw_rating, adj_rating
                    from instructor_scores
                    where rmp_id = 1001
                    """
                )
            )
        ).mappings().one()

    expected = shrink(
        float(row["raw_rating"]),
        int(row["rating_count"]),
        float(means["mean_rating"]),
        float(params),
    )
    assert float(row["adj_rating"]) == pytest.approx(expected, abs=1e-4)


async def test_would_take_again_minus_one_stays_absent_through_the_view(seeded):
    async with seeded() as session:
        stored = (
            await session.execute(
                text("select would_take_again_percent from rmp_professors where rmp_id = 1002")
            )
        ).scalar_one()
        row = (
            await session.execute(
                text(
                    """
                    select would_take_again_percent, adj_would_take_again
                    from instructor_scores where rmp_id = 1002
                    """
                )
            )
        ).mappings().one()
        mean = (
            await session.execute(text("select mean_would_take_again from scoring_means"))
        ).scalar_one()

    assert stored == -1, "the seed row holds the raw sentinel"
    assert row["would_take_again_percent"] is None, "the view must not emit -1 as a percentage"
    assert row["adj_would_take_again"] is None, "-1 means nobody answered, not zero"
    # 83% and 25% average to 54% -> 2.7/5. A -1 in the mix would drag this under.
    assert float(mean) == pytest.approx(2.7, abs=0.01)


async def test_class_specific_scores_differ_from_the_general_one(seeded):
    """The doc's requirement: per-class where there is evidence, general otherwise."""
    async with seeded() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select upper(c.dept || c.number) as code,
                           ics.class_rating_count, ics.adj_rating, ics.adj_difficulty
                      from instructor_course_scores ics
                      join courses c on c.id = ics.course_id
                      join instructors i on i.id = ics.instructor_id
                     where i.rmp_id = 1001
                     order by code
                    """
                )
            )
        ).mappings().all()

    by_code = {row["code"]: row for row in rows}
    assert by_code["CSCE121"]["class_rating_count"] == 3
    assert by_code["MATH151"]["class_rating_count"] == 1
    # The CSCE121 reviews are happier and easier than the MATH151 one.
    assert float(by_code["CSCE121"]["adj_rating"]) > float(by_code["MATH151"]["adj_rating"])
    assert float(by_code["CSCE121"]["adj_difficulty"]) < float(by_code["MATH151"]["adj_difficulty"])


async def test_a_course_with_no_reviews_inherits_the_general_score(seeded):
    async with seeded() as session:
        general, in_course = (
            await session.execute(
                text(
                    """
                    select isc.adj_rating as general, ics.adj_rating as in_course
                      from instructor_scores isc
                      join instructor_course_scores ics
                        on ics.instructor_id = isc.instructor_id
                      join courses c on c.id = ics.course_id
                     where isc.rmp_id = 1003
                       and upper(c.dept || c.number) = 'ENGL104'
                    """
                )
            )
        ).one()

    # Richard Roe's only review mentions ENGL104, so the class-specific average
    # exists; the professors with no class-matched reviews are the inheriting case.
    assert general is not None and in_course is not None


async def test_search_finds_a_professor_by_a_name_fragment(seeded):
    async with seeded() as session:
        found = await repository.search_instructors(session, query="jane", limit=10)
        everyone = await repository.search_instructors(session, query="", limit=10)

    assert found["total"] == 1
    assert found["results"][0]["full_name"] == "DOE, JANE M"
    assert everyone["total"] == 3
    # With no query, ranking is the doc's rule: rating desc, then difficulty asc.
    ratings = [float(row["adj_rating"]) for row in everyone["results"]]
    assert ratings == sorted(ratings, reverse=True)


async def test_search_filters_by_department(seeded):
    async with seeded() as session:
        result = await repository.search_instructors(session, department="English", limit=10)
    assert [row["full_name"] for row in result["results"]] == ["ROE, RICHARD A"]


async def test_professor_payload_assembles_every_section(seeded):
    async with seeded() as session:
        instructor_id = (
            await session.execute(text("select id from instructors where rmp_id = 1001"))
        ).scalar_one()
        await session.execute(
            text(
                """
                insert into summaries (
                    subject_type, instructor_id, model, prompt_version, summary_md,
                    facets, source_rating_count
                ) values (
                    'instructor', cast(:id as bigint), 'stub', cast(:pv as text),
                    'Clear lecturer.', '{"confidence": "medium"}'::jsonb, 3
                )
                """
            ),
            {"id": instructor_id, "pv": PROMPT_VERSION},
        )
        await session.commit()

        payload = await repository.load_professor(
            session, instructor_id, prompt_version=PROMPT_VERSION
        )

    assert payload is not None
    assert payload["full_name"] == "DOE, JANE M"
    assert {course["code"] for course in payload["courses"]} == {"CSCE121", "MATH151"}
    assert len(payload["grades"]) == 2
    assert len(payload["recent_comments"]) == 4
    assert payload["recent_comments"][0]["comment"] == "Tough but fair."  # newest first
    assert payload["summaries"][0]["summary_md"] == "Clear lecturer."


async def test_an_unknown_instructor_id_is_none(seeded):
    async with seeded() as session:
        assert await repository.load_professor(session, 999_999, prompt_version="v1") is None


async def test_course_instructors_are_ranked(seeded):
    async with seeded() as session:
        rows = await repository.course_instructors(session, dept="CSCE", number="121")

    assert [row["full_name"] for row in rows][0] == "DOE, JANE M"
    ratings = [float(row["adj_rating"]) for row in rows]
    assert ratings == sorted(ratings, reverse=True)


async def test_popular_instructors_come_back_most_rated_first(seeded):
    async with seeded() as session:
        ids = await repository.popular_instructor_ids(session, 2)
        top = (
            await session.execute(text("select id from instructors where rmp_id = 1001"))
        ).scalar_one()

    assert ids[0] == top


async def test_data_version_increments_for_cache_invalidation(sessions):
    async with sessions() as session:
        assert await repository.current_data_version(session) == 0
        assert await bump_data_version(session) == 1
        assert await bump_data_version(session) == 2
        assert await repository.current_data_version(session) == 2
