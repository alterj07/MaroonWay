-- MaroonWay schema. Paste into the Supabase SQL editor (Project -> SQL Editor),
-- or apply with: python -m app.ingest.apply_sql sql/001_schema.sql
--
-- Mirrored by app/models.py. Change both.

create extension if not exists pg_trgm;

-- One row, one integer. Every ingest job bumps it, and the API puts it in every
-- cache key -- so reloading data invalidates the whole hot cache in one step
-- instead of serving a blend of old and new rows.
create table if not exists data_version (
    id          smallint primary key default 1 check (id = 1),
    version     integer     not null default 0,
    updated_at  timestamptz not null default now()
);
insert into data_version (id, version) values (1, 0) on conflict (id) do nothing;

-- The join point between the grades CSV and RateMyProfessors.
-- canonical_key is name_tokens() sorted and joined, so "DOE JOHN" and
-- "John Doe" collide on purpose. Two genuinely different professors with the
-- same name would collide too; name_links records how each link was made so
-- that is visible rather than silent.
create table if not exists instructors (
    id               bigserial primary key,
    full_name        text not null,
    normalized_name  text not null,
    canonical_key    text not null unique,
    department       text,
    rmp_id           bigint unique,
    created_at       timestamptz not null default now()
);

-- One row per catalog course. Where it is *offered* (campus) belongs to the
-- offering, not the course, so that lives on course_grades and sections.
create table if not exists courses (
    id              bigserial primary key,
    dept            text not null,
    number          text not null,
    title           text,
    honors          boolean not null default false,
    level           text,
    credits         text,
    description     text,
    -- The planning doc's "Prereqs" requirement, straight from the catalog.
    prereq_text     text,
    coreq_text      text,
    is_honors_dept  boolean,
    constraint courses_identity unique nulls not distinct (dept, number, honors)
);

-- One row per row of the grades CSV.
create table if not exists course_grades (
    id             bigserial primary key,
    instructor_id  bigint references instructors (id) on delete cascade,
    course_id      bigint not null references courses (id) on delete cascade,
    term           text not null,
    term_year      smallint,
    term_season    text check (term_season in ('spring', 'summer', 'fall')),
    section        text,
    campus         text,
    level          text,
    -- Which grade-report PDF this row was parsed out of.
    source_file    text,
    grade_a        integer,
    grade_b        integer,
    grade_c        integer,
    grade_d        integer,
    grade_f        integer,
    grade_q        integer,
    grade_i        integer,
    grade_s        integer,
    grade_u        integer,
    grade_x        integer,
    af_total       integer,
    enrolled       integer,
    gpa            numeric(4, 3),
    source_row     integer,
    constraint course_grades_identity
        unique nulls not distinct (instructor_id, course_id, term, section)
);

create table if not exists rmp_professors (
    rmp_id                   bigint primary key,
    -- The base64 GraphQL node id from the school listing. Keeping it means the
    -- comment fetch is one request instead of two (the package otherwise
    -- scrapes an HTML page just to re-derive this).
    node_id                  text,
    first_name               text,
    last_name                text,
    full_name                text,
    department               text,
    school_id                text,
    avg_rating               numeric(4, 2),
    avg_difficulty           numeric(4, 2),
    num_ratings              integer not null default 0,
    -- Aggregate only. The scraper exposes no per-review would-take-again, so
    -- this weights a professor and never a single class.
    would_take_again_percent numeric(5, 2),
    ratings_distribution     jsonb,
    -- [{"courseName": "CSCE121", "courseCount": 14}] -- what they actually teach.
    course_codes             jsonb,
    rmp_url                  text,
    reviews_window_start     timestamptz,
    reviews_window_end       timestamptz,
    fetched_at               timestamptz not null default now(),
    -- Set once comments have been pulled, not just the listing aggregates.
    details_fetched_at       timestamptz
);

create table if not exists rmp_ratings (
    id          bigserial primary key,
    rmp_id      bigint not null references rmp_professors (rmp_id) on delete cascade,
    -- RateMyProfessors' own id for the review. Present when the review came
    -- from the data pipeline, which makes upserts exact instead of heuristic.
    rmp_rating_id bigint,
    -- Set when the review was collected as being about a specific course.
    course_id   bigint references courses (id) on delete set null,
    class_code  text,
    comment     text,
    helpful     numeric(4, 2),
    clarity     numeric(4, 2),
    difficulty  numeric(4, 2),
    rated_at    timestamptz,
    -- Two planning-doc requirements the scraper does expose per review:
    -- "Web vs F2F" and "Attendance".
    is_online            boolean,
    attendance_mandatory boolean,
    textbook_use         text,
    is_for_credit        boolean,
    -- Three fields the pinned scraper package drops but the data pipeline kept:
    -- the letter grade the student reported, their own would-take-again answer
    -- (the package exposes only the professor-level percentage), and the tags.
    grade                text,
    would_take_again     boolean,
    rating_tags          text,
    thumbs_up            integer,
    thumbs_down          integer,
    course_match_status  text,
    -- The untouched scraper payload, so fields it starts returning later need
    -- no migration to be useful.
    raw         jsonb not null default '{}'::jsonb,
    constraint rmp_ratings_identity
        unique nulls not distinct (rmp_id, class_code, rated_at, comment)
);

-- The unique constraint is what makes the Gemini batch job resumable: a row
-- that already exists for this prompt_version is skipped, so a run interrupted
-- by a 429 picks up where it stopped.
create table if not exists summaries (
    id                  bigserial primary key,
    subject_type        text not null check (subject_type in ('instructor', 'instructor_course')),
    instructor_id       bigint not null references instructors (id) on delete cascade,
    course_id           bigint references courses (id) on delete cascade,
    model               text not null,
    prompt_version      text not null,
    window_start        timestamptz,
    window_end          timestamptz,
    summary_md          text not null,
    facets              jsonb not null default '{}'::jsonb,
    source_rating_count integer not null default 0,
    generated_at        timestamptz not null default now(),
    constraint summaries_identity
        unique nulls not distinct (subject_type, instructor_id, course_id, prompt_version)
);

-- Populated once real meeting times exist; seeded from tests/fixtures until
-- then, so the 20-minute-gap scheduler can be built and tested now.
create table if not exists sections (
    id             bigserial primary key,
    course_id      bigint not null references courses (id) on delete cascade,
    instructor_id  bigint references instructors (id) on delete set null,
    term           text not null,
    section_code   text not null,
    campus         text check (campus in ('CSTAT', 'BLINN')),
    delivery       text check (delivery in ('F2F', 'WEB', 'HYBRID')),
    honors         boolean not null default false,
    -- [{"day": "MON", "start": "09:10", "end": "10:00", "building": "ZACH", "room": "350"}]
    meets          jsonb not null default '[]'::jsonb,
    seats          integer,
    seats_open     integer,
    constraint sections_identity unique (term, course_id, section_code)
);

-- The audit trail for name matching: every link, its method, its confidence.
-- A wrong match is fixable by hand because it is written down here.
create table if not exists name_links (
    id               bigserial primary key,
    source           text not null default 'grades_csv',
    source_name      text not null,
    normalized_name  text not null,
    instructor_id    bigint references instructors (id) on delete cascade,
    rmp_id           bigint,
    method           text not null,
    confidence       numeric(5, 2) not null,
    linked_at        timestamptz not null default now(),
    constraint name_links_identity unique (source, source_name)
);
