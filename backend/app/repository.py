"""Every SQL statement the API runs, in one place.

Routers call these; nothing else touches the database. That keeps the cache
layer honest -- it is obvious what a cache miss actually costs -- and lets tests
substitute a fake loader without a database.

Parameters are explicitly cast (``cast(:q as text)``) because asyncpg refuses to
infer a parameter's type from context the way psycopg does.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SCORE_COLUMNS = """
    s.instructor_id, s.full_name, s.department, s.rmp_id, s.rating_count,
    s.raw_rating, s.raw_difficulty, s.would_take_again_percent,
    s.adj_rating, s.adj_difficulty, s.adj_would_take_again, s.adj_gpa
"""

_DATA_VERSION = text("select version from data_version where id = 1")

_SEARCH = text(
    f"""
    select {SCORE_COLUMNS},
        case
            when cast(:q as text) = '' then 0
            else similarity(i.normalized_name, cast(:q as text))
        end as name_similarity
    from instructor_scores s
    join instructors i on i.id = s.instructor_id
    where (
            cast(:q as text) = ''
            or i.normalized_name ilike '%' || cast(:q as text) || '%'
            or similarity(i.normalized_name, cast(:q as text)) > 0.3
        )
      and (cast(:dept as text) is null or s.department = cast(:dept as text))
    order by name_similarity desc, s.adj_rating desc, s.adj_difficulty asc
    limit cast(:limit as integer) offset cast(:offset as integer)
    """
)

_SEARCH_COUNT = text(
    """
    select count(*)
    from instructor_scores s
    join instructors i on i.id = s.instructor_id
    where (
            cast(:q as text) = ''
            or i.normalized_name ilike '%' || cast(:q as text) || '%'
            or similarity(i.normalized_name, cast(:q as text)) > 0.3
        )
      and (cast(:dept as text) is null or s.department = cast(:dept as text))
    """
)

_PROFESSOR = text(
    f"""
    select {SCORE_COLUMNS}
    from instructor_scores s
    where s.instructor_id = cast(:instructor_id as bigint)
    """
)

_PROFESSOR_COURSES = text(
    """
    select
        ics.course_id,
        c.dept, c.number, c.title, c.honors, ics.campus,
        upper(c.dept || c.number) as code,
        ics.class_rating_count, ics.section_count,
        ics.adj_rating, ics.adj_difficulty, ics.adj_would_take_again, ics.adj_gpa,
        ics.raw_gpa
    from instructor_course_scores ics
    join courses c on c.id = ics.course_id
    where ics.instructor_id = cast(:instructor_id as bigint)
    order by ics.adj_rating desc, ics.adj_difficulty asc
    """
)

_PROFESSOR_GRADES = text(
    """
    select
        upper(c.dept || c.number) as code, c.title,
        g.term, g.term_year, g.term_season, g.section, g.gpa, g.enrolled,
        g.grade_a, g.grade_b, g.grade_c, g.grade_d, g.grade_f, g.grade_q
    from course_grades g
    join courses c on c.id = g.course_id
    where g.instructor_id = cast(:instructor_id as bigint)
    order by g.term_year desc nulls last, g.term desc, code
    limit cast(:limit as integer)
    """
)

_PROFESSOR_COMMENTS = text(
    """
    select r.class_code, r.comment, r.helpful, r.clarity, r.difficulty, r.rated_at
    from rmp_ratings r
    where r.rmp_id = cast(:rmp_id as bigint)
      and r.comment is not null
      and length(btrim(r.comment)) > 0
    order by r.rated_at desc nulls last
    limit cast(:limit as integer)
    """
)

_PROFESSOR_SUMMARIES = text(
    """
    select
        s.subject_type, s.course_id,
        case when c.id is null then null else upper(c.dept || c.number) end as course_code,
        s.model, s.prompt_version, s.summary_md, s.facets,
        s.window_start, s.window_end, s.source_rating_count, s.generated_at
    from summaries s
    left join courses c on c.id = s.course_id
    where s.instructor_id = cast(:instructor_id as bigint)
      and s.prompt_version = cast(:prompt_version as text)
    order by s.subject_type, course_code nulls first
    """
)

_COURSE_INSTRUCTORS = text(
    """
    select
        ics.instructor_id, i.full_name, i.department, i.rmp_id,
        ics.class_rating_count, ics.instructor_rating_count, ics.section_count,
        ics.adj_rating, ics.adj_difficulty, ics.adj_would_take_again, ics.adj_gpa
    from instructor_course_scores ics
    join instructors i on i.id = ics.instructor_id
    join courses c on c.id = ics.course_id
    where upper(c.dept) = upper(cast(:dept as text))
      and c.number = cast(:number as text)
    order by ics.adj_rating desc, ics.adj_difficulty asc
    limit cast(:limit as integer)
    """
)

_POPULAR_INSTRUCTORS = text(
    """
    select s.instructor_id
    from instructor_scores s
    order by s.rating_count desc, s.adj_rating desc
    limit cast(:limit as integer)
    """
)


async def current_data_version(session: AsyncSession) -> int:
    row = (await session.execute(_DATA_VERSION)).first()
    return int(row[0]) if row else 0


async def search_instructors(
    session: AsyncSession,
    *,
    query: str = "",
    department: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    params = {
        "q": (query or "").strip().lower(),
        "dept": department,
        "limit": limit,
        "offset": offset,
    }
    rows = (await session.execute(_SEARCH, params)).mappings().all()
    total = (await session.execute(_SEARCH_COUNT, params)).scalar_one()
    return {
        "query": params["q"],
        "department": department,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": [dict(row) for row in rows],
    }


async def load_professor(
    session: AsyncSession,
    instructor_id: int,
    *,
    prompt_version: str,
    comment_limit: int = 25,
    grade_limit: int = 60,
) -> dict[str, Any] | None:
    """The whole professor page in one payload, or ``None`` if there is no such id.

    This is the expensive read the hot cache fronts: five queries, one of which
    touches every rating the professor has.
    """
    profile = (
        await session.execute(_PROFESSOR, {"instructor_id": instructor_id})
    ).mappings().first()
    if profile is None:
        return None

    payload: dict[str, Any] = dict(profile)
    payload["courses"] = [
        dict(row)
        for row in (
            await session.execute(_PROFESSOR_COURSES, {"instructor_id": instructor_id})
        )
        .mappings()
        .all()
    ]
    payload["grades"] = [
        dict(row)
        for row in (
            await session.execute(
                _PROFESSOR_GRADES, {"instructor_id": instructor_id, "limit": grade_limit}
            )
        )
        .mappings()
        .all()
    ]
    payload["summaries"] = [
        dict(row)
        for row in (
            await session.execute(
                _PROFESSOR_SUMMARIES,
                {"instructor_id": instructor_id, "prompt_version": prompt_version},
            )
        )
        .mappings()
        .all()
    ]
    rmp_id = payload.get("rmp_id")
    payload["recent_comments"] = (
        [
            dict(row)
            for row in (
                await session.execute(
                    _PROFESSOR_COMMENTS, {"rmp_id": rmp_id, "limit": comment_limit}
                )
            )
            .mappings()
            .all()
        ]
        if rmp_id is not None
        else []
    )
    return payload


async def course_instructors(
    session: AsyncSession,
    *,
    dept: str,
    number: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            _COURSE_INSTRUCTORS, {"dept": dept, "number": number, "limit": limit}
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def popular_instructor_ids(session: AsyncSession, limit: int) -> list[int]:
    """Most-rated professors first -- a decent proxy for "who gets looked up"."""
    rows = (await session.execute(_POPULAR_INSTRUCTORS, {"limit": limit})).all()
    return [int(row[0]) for row in rows]


_SECTIONS_FOR_COURSES = text(
    """
    select
        s.id            as section_id,
        s.course_id,
        upper(c.dept || c.number) as code,
        s.section_code,
        s.term,
        s.instructor_id,
        i.full_name     as instructor_name,
        s.campus,
        s.delivery,
        s.honors,
        s.seats,
        s.seats_open,
        s.meets,
        ics.adj_rating,
        ics.adj_difficulty,
        ics.adj_gpa,
        ics.pct_a
    from sections s
    join courses c on c.id = s.course_id
    left join instructors i on i.id = s.instructor_id
    left join instructor_course_scores ics
        on ics.instructor_id = s.instructor_id and ics.course_id = s.course_id
    where s.term = cast(:term as text)
      and upper(c.dept || c.number) = any(cast(:codes as text[]))
      and (cast(:campus as text) is null or s.campus is null or s.campus = cast(:campus as text))
      and (cast(:honors as boolean) is null or s.honors = cast(:honors as boolean))
      and (cast(:delivery as text) is null or s.delivery is null or s.delivery = cast(:delivery as text))
      and (not cast(:open_only as boolean) or coalesce(s.seats_open, 1) > 0)
    order by code, s.section_code
    """
)

async def sections_for_courses(
    session: AsyncSession,
    *,
    term: str,
    codes: list[str],
    campus: str | None = None,
    honors: bool | None = None,
    delivery: str | None = None,
    open_only: bool = False,
) -> list[dict[str, Any]]:
    """Every section of the requested courses, with its instructor's scores.

    Filters that the data may not know are permissive: a section with a null
    campus is not excluded by a campus filter, because excluding it would hide
    a real class over missing metadata.
    """
    rows = (
        await session.execute(
            _SECTIONS_FOR_COURSES,
            {
                "term": term,
                "codes": [code.upper() for code in codes],
                "campus": campus,
                "honors": honors,
                "delivery": delivery,
                "open_only": open_only,
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def available_terms(session: AsyncSession) -> list[dict[str, Any]]:
    """Terms that have sections loaded, and how many carry meeting times."""
    rows = (
        await session.execute(
            text(
                """
                select term,
                       count(*) as sections,
                       count(*) filter (where meets <> '[]'::jsonb) as with_times
                from sections
                group by term
                order by term desc
                """
            )
        )
    ).mappings().all()
    return [dict(row) for row in rows]


_TRAITS = text(
    """
    select instructor_id, course_id, lots_of_quizzes, exam_difficulty,
           lecture_quality, attendance_taken, extra_credit, heavy_workload,
           grades_generously, confidence, model, review_count
    from instructor_traits
    where instructor_id = any(cast(:instructor_ids as bigint[]))
      and question_version = cast(:version as text)
    """
)


async def traits_for_instructors(
    session: AsyncSession,
    instructor_ids: list[int],
    *,
    version: str,
) -> list[dict[str, Any]]:
    """Jev's decisions about these professors, overall and per course."""
    if not instructor_ids:
        return []
    rows = (
        await session.execute(
            _TRAITS, {"instructor_ids": instructor_ids, "version": version}
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def courses_with_sections(
    session: AsyncSession, *, term: str, limit: int = 200
) -> list[dict[str, Any]]:
    """Courses a student could actually build a schedule from this term.

    Ordered by how much choice they offer, so a picker (or a demo) can lead
    with courses that have several professors and times.
    """
    rows = (
        await session.execute(
            text(
                """
                select
                    upper(c.dept || c.number) as code,
                    c.dept,
                    c.number,
                    c.title,
                    count(*)                            as sections,
                    count(distinct s.instructor_id)     as instructors,
                    count(*) filter (where s.meets <> '[]'::jsonb) as with_times
                from sections s
                join courses c on c.id = s.course_id
                where s.term = cast(:term as text)
                group by c.dept, c.number, c.title
                order by count(distinct s.instructor_id) desc, code
                limit cast(:limit as integer)
                """
            ),
            {"term": term, "limit": limit},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


_EXPLORE = text(
    """
    with ranked as (
        select
            c.id                        as course_id,
            upper(c.dept || c.number)   as code,
            c.dept, c.number, c.title, c.credits, c.honors, c.prereq_text,
            i.id                        as instructor_id,
            i.full_name                 as instructor_name,
            ics.adj_rating, ics.adj_difficulty, ics.adj_gpa, ics.pct_a,
            ics.class_rating_count, ics.instructor_rating_count, ics.section_count
        from courses c
        left join instructor_course_scores ics on ics.course_id = c.id
        left join instructors i on i.id = ics.instructor_id
        where (
                cast(:q as text) = ''
                -- Codes are stored compact ("CSCE121") and typed either way,
                -- so the query loses its spaces for this comparison only.
                or upper(c.dept || c.number) like
                   upper('%' || replace(cast(:q as text), ' ', '') || '%')
                or c.title ilike '%' || cast(:q as text) || '%'
                or i.normalized_name ilike '%' || lower(cast(:q as text)) || '%'
              )
    )
    select
        course_id, code, dept, number, title, credits, honors, prereq_text,
        count(instructor_id)                                      as professor_count,
        avg(adj_rating)                                           as avg_rating,
        avg(pct_a)                                                as avg_pct_a,
        coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'instructor_id', instructor_id,
                    'name', instructor_name,
                    'adj_rating', adj_rating,
                    'adj_difficulty', adj_difficulty,
                    'adj_gpa', adj_gpa,
                    'pct_a', pct_a,
                    'class_reviews', class_rating_count,
                    'professor_reviews', instructor_rating_count,
                    'sections', section_count
                )
                order by adj_rating desc nulls last
            ) filter (where instructor_id is not null),
            '[]'::jsonb
        )                                                         as professors
    from ranked
    group by course_id, code, dept, number, title, credits, honors, prereq_text
    order by count(instructor_id) desc, code
    limit cast(:limit as integer)
    """
)


async def explore_courses(
    session: AsyncSession,
    *,
    query: str = "",
    limit: int = 60,
    professors_per_course: int = 8,
) -> list[dict[str, Any]]:
    """Courses with every professor who has taught them, best rated first.

    One query rather than one per card: the course explorer needs the
    professors *on* the card, so a student can tell a good instructor from a
    bad one without clicking through.
    """
    rows = (
        await session.execute(_EXPLORE, {"q": (query or "").strip(), "limit": limit})
    ).mappings().all()
    courses = []
    for row in rows:
        course = dict(row)
        course["professors"] = (course.get("professors") or [])[:professors_per_course]
        courses.append(course)
    return courses
