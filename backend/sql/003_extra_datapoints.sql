-- Datapoints the CSVs carry that the first schema dropped on the floor.
--
-- Three of them are organisational: the grade reports name a college and a
-- department per row, and the catalog implies an undergraduate/graduate level
-- from the course number. The fourth is the useful one: the dataset records
-- which terms each instructor actually taught each course, which is the only
-- evidence we have about who is likely to teach it again.

alter table course_grades add column if not exists college    text;
alter table course_grades add column if not exists department text;

alter table courses add column if not exists dept_code text;

-- Which terms an instructor has taught a course, from grade_terms_json.
--
-- One row per (instructor, course, term) rather than a JSON blob per pair, so
-- "who teaches ENGR102 in the fall" is an index scan instead of a scan plus a
-- JSON walk. Seasons are the same three the grade data uses.
create table if not exists instructor_course_terms (
    instructor_id bigint not null references instructors (id) on delete cascade,
    course_id     bigint not null references courses (id) on delete cascade,
    term          text   not null,
    term_year     smallint,
    term_season   text check (term_season in ('spring', 'summer', 'fall')),
    primary key (instructor_id, course_id, term)
);

create index if not exists instructor_course_terms_course_season_idx
    on instructor_course_terms (course_id, term_season, term_year desc);
create index if not exists instructor_course_terms_recent_idx
    on instructor_course_terms (course_id, term_year desc);

create index if not exists course_grades_college_idx
    on course_grades (college) where college is not null;
create index if not exists course_grades_campus_idx
    on course_grades (campus) where campus is not null;

-- A&M runs sections at Galveston and in Qatar too, and the grade data covers
-- both; the original check allowed only College Station and Blinn, so loading
-- a Galveston section failed outright.
alter table sections drop constraint if exists sections_campus_check;
alter table sections add constraint sections_campus_check
    check (campus in ('CSTAT', 'BLINN', 'GALV', 'QATAR'));
