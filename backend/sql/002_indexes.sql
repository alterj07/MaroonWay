-- Indexes and the scoring views. Apply after 001_schema.sql.
--
-- The views are the serving path for ranking: always current, no recompute job.
-- app/scoring.py mirrors this arithmetic and is what the unit tests check --
-- change one, change both.

create index if not exists instructors_normalized_trgm
    on instructors using gin (normalized_name gin_trgm_ops);
create index if not exists instructors_department_idx on instructors (department);
create index if not exists courses_code_idx on courses (dept, number);
create index if not exists course_grades_instructor_idx on course_grades (instructor_id);
create index if not exists course_grades_course_idx on course_grades (course_id);
create index if not exists rmp_ratings_recent_idx on rmp_ratings (rmp_id, rated_at desc);
create index if not exists rmp_ratings_class_idx on rmp_ratings (class_code);
create index if not exists rmp_ratings_course_idx on rmp_ratings (course_id);
-- Exact upserts for reviews that carry RateMyProfessors' own id.
create unique index if not exists rmp_ratings_rating_id_key
    on rmp_ratings (rmp_rating_id) where rmp_rating_id is not null;
create index if not exists summaries_lookup_idx
    on summaries (instructor_id, course_id, prompt_version);
create index if not exists sections_term_idx on sections (term, course_id);
create index if not exists instructor_traits_lookup_idx
    on instructor_traits (instructor_id, course_id);
-- Which professors still need their comments pulled.
create index if not exists rmp_professors_details_idx
    on rmp_professors (details_fetched_at nulls first, num_ratings desc);

-- Dropped first, in reverse dependency order: CREATE OR REPLACE VIEW cannot
-- change a view's column list, so without these an applied change to the shape
-- of a view fails silently against an existing database.
drop view if exists instructor_course_scores;
drop view if exists instructor_scores;
drop view if exists instructor_gpa;
drop view if exists scoring_means;
drop view if exists scoring_params;

-- How many ratings it takes before a professor's own average outweighs the
-- global mean. One place to change it.
create or replace view scoring_params as
select 10.0::numeric as prior_weight;

-- The priors. 4.9-from-two-reviews gets pulled toward these; 4.6-from-eighty
-- barely moves.
create or replace view scoring_means as
select
    coalesce(avg(p.avg_rating) filter (where p.num_ratings > 0), 3.5)::numeric      as mean_rating,
    coalesce(avg(p.avg_difficulty) filter (where p.num_ratings > 0), 3.0)::numeric  as mean_difficulty,
    -- RMP writes -1 for "nobody answered"; averaging that in would drag the
    -- prior down with non-data.
    coalesce(
        avg(p.would_take_again_percent) filter (where p.would_take_again_percent >= 0)
        / 100.0 * 5.0,
        3.0
    )::numeric                                                                      as mean_would_take_again,
    (select coalesce(avg(gpa), 3.0) from course_grades where gpa is not null)::numeric as mean_gpa
from rmp_professors p;

-- Enrolment-weighted GPA per professor across everything they have taught.
create or replace view instructor_gpa as
select
    instructor_id,
    sum(gpa * coalesce(enrolled, 1)) / nullif(sum(coalesce(enrolled, 1)), 0) as avg_gpa,
    sum(coalesce(enrolled, 1))                                              as student_count,
    count(*)                                                                as section_count
from course_grades
where instructor_id is not null and gpa is not null
group by instructor_id;

-- One row per professor: raw inputs plus the shrunk values the API ranks on.
-- The weighted composite is deliberately NOT here -- weights live in settings
-- and are applied in Python, so there is one source of truth for each half.
create or replace view instructor_scores as
select
    i.id                                        as instructor_id,
    i.full_name,
    -- The CSV rarely carries a department; RMP does.
    coalesce(i.department, r.department)        as department,
    i.rmp_id,
    coalesce(r.num_ratings, 0)                  as rating_count,
    r.avg_rating                                as raw_rating,
    r.avg_difficulty                            as raw_difficulty,
    -- Sanitised here as well as in the loader: nothing downstream should ever
    -- see -1 as a percentage.
    nullif(greatest(r.would_take_again_percent, -1), -1) as would_take_again_percent,
    g.avg_gpa                                   as raw_gpa,
    coalesce(g.student_count, 0)                as gpa_student_count,
    (
        (coalesce(r.num_ratings, 0) * coalesce(r.avg_rating, m.mean_rating)
         + p.prior_weight * m.mean_rating)
        / (coalesce(r.num_ratings, 0) + p.prior_weight)
    )::numeric(6, 4)                            as adj_rating,
    (
        (coalesce(r.num_ratings, 0) * coalesce(r.avg_difficulty, m.mean_difficulty)
         + p.prior_weight * m.mean_difficulty)
        / (coalesce(r.num_ratings, 0) + p.prior_weight)
    )::numeric(6, 4)                            as adj_difficulty,
    case
        when r.would_take_again_percent is null or r.would_take_again_percent < 0 then null
        else (
            (coalesce(r.num_ratings, 0) * (r.would_take_again_percent / 100.0 * 5.0)
             + p.prior_weight * m.mean_would_take_again)
            / (coalesce(r.num_ratings, 0) + p.prior_weight)
        )::numeric(6, 4)
    end                                         as adj_would_take_again,
    case
        when g.avg_gpa is null then null
        else (
            (
                (coalesce(g.student_count, 0) * g.avg_gpa + p.prior_weight * m.mean_gpa)
                / (coalesce(g.student_count, 0) + p.prior_weight)
            ) / 4.0 * 5.0
        )::numeric(6, 4)
    end                                         as adj_gpa
from instructors i
left join rmp_professors r on r.rmp_id = i.rmp_id
left join instructor_gpa g on g.instructor_id = i.id
cross join scoring_params p
cross join scoring_means m;

-- One row per professor x course. This is the doc's "differentiate the class
-- from each RMP rating by class, but keep the general teaching style from ALL
-- ratings": a class-specific average is shrunk toward that professor's own
-- overall adjusted value, so three reviews of CSCE121 nudge the number rather
-- than replacing it, and a class with no reviews of its own inherits the
-- professor's general score.
create or replace view instructor_course_scores as
with course_code as (
    select id as course_id, upper(dept || number) as code from courses
),
class_ratings as (
    select
        i.id                                    as instructor_id,
        cc.course_id,
        count(*)                                as class_rating_count,
        -- RMP's per-review star rating is the mean of its helpful and clarity
        -- scores; the scraper exposes those two, not the star itself.
        avg((coalesce(rr.helpful, rr.clarity) + coalesce(rr.clarity, rr.helpful)) / 2.0) as avg_rating,
        avg(rr.difficulty)                      as avg_difficulty
    from rmp_ratings rr
    join instructors i on i.rmp_id = rr.rmp_id
    join course_code cc
        on cc.code = upper(regexp_replace(coalesce(rr.class_code, ''), '[^A-Za-z0-9]', '', 'g'))
    group by i.id, cc.course_id
),
course_gpa_mean as (
    select
        course_id,
        sum(gpa * coalesce(enrolled, 1)) / nullif(sum(coalesce(enrolled, 1)), 0) as mean_gpa
    from course_grades
    where gpa is not null
    group by course_id
),
instructor_course_gpa as (
    select
        instructor_id,
        course_id,
        sum(gpa * coalesce(enrolled, 1)) / nullif(sum(coalesce(enrolled, 1)), 0) as avg_gpa,
        sum(coalesce(enrolled, 1))                                              as student_count,
        count(*)                                                                as section_count,
        -- The share of students who got an A. The planning doc asks for grades,
        -- and this is the form a student actually reads.
        sum(coalesce(grade_a, 0))::numeric / nullif(sum(coalesce(enrolled, 0)), 0) as pct_a,
        -- Campus is a property of the offering, not the course, so it is
        -- aggregated from the sections actually taught. Null until the section
        -- data carries a campus column.
        mode() within group (order by campus)                                   as campus
    from course_grades
    where instructor_id is not null and gpa is not null
    group by instructor_id, course_id
)
select
    coalesce(icg.instructor_id, cr.instructor_id)   as instructor_id,
    coalesce(icg.course_id, cr.course_id)           as course_id,
    coalesce(cr.class_rating_count, 0)              as class_rating_count,
    isc.rating_count                                as instructor_rating_count,
    coalesce(icg.section_count, 0)                  as section_count,
    icg.campus,
    icg.pct_a,
    icg.avg_gpa                                     as raw_gpa,
    case
        when coalesce(cr.class_rating_count, 0) = 0 or cr.avg_rating is null then isc.adj_rating
        else (
            (cr.class_rating_count * cr.avg_rating + p.prior_weight * isc.adj_rating)
            / (cr.class_rating_count + p.prior_weight)
        )::numeric(6, 4)
    end                                             as adj_rating,
    case
        when coalesce(cr.class_rating_count, 0) = 0 or cr.avg_difficulty is null
            then isc.adj_difficulty
        else (
            (cr.class_rating_count * cr.avg_difficulty + p.prior_weight * isc.adj_difficulty)
            / (cr.class_rating_count + p.prior_weight)
        )::numeric(6, 4)
    end                                             as adj_difficulty,
    isc.adj_would_take_again,
    case
        when icg.avg_gpa is null then isc.adj_gpa
        else (
            (
                (icg.student_count * icg.avg_gpa
                 + p.prior_weight * coalesce(cgm.mean_gpa, m.mean_gpa))
                / (icg.student_count + p.prior_weight)
            ) / 4.0 * 5.0
        )::numeric(6, 4)
    end                                             as adj_gpa
from instructor_course_gpa icg
full outer join class_ratings cr
    on cr.instructor_id = icg.instructor_id and cr.course_id = icg.course_id
join instructor_scores isc
    on isc.instructor_id = coalesce(icg.instructor_id, cr.instructor_id)
left join course_gpa_mean cgm on cgm.course_id = coalesce(icg.course_id, cr.course_id)
cross join scoring_params p
cross join scoring_means m;
