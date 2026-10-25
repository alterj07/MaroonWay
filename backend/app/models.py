"""SQLAlchemy Core tables, mirroring sql/001_schema.sql.

Used by the ingest jobs for typed upserts (``on_conflict_do_update`` against the
named constraints). The SQL files remain what you actually apply to Supabase --
these definitions exist so ingest code does not hand-write INSERT statements.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

data_version = Table(
    "data_version",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("version", Integer, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

instructors = Table(
    "instructors",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("full_name", Text, nullable=False),
    Column("normalized_name", Text, nullable=False),
    Column("canonical_key", Text, nullable=False, unique=True),
    Column("department", Text),
    Column("rmp_id", BigInteger, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

courses = Table(
    "courses",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("dept", Text, nullable=False),
    Column("number", Text, nullable=False),
    Column("title", Text),
    Column("honors", Boolean, nullable=False, server_default="false"),
    Column("level", Text),
    Column("credits", Text),
    Column("description", Text),
    Column("prereq_text", Text),
    Column("coreq_text", Text),
    Column("is_honors_dept", Boolean),
)

course_grades = Table(
    "course_grades",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("instructor_id", BigInteger, ForeignKey("instructors.id", ondelete="CASCADE")),
    Column("course_id", BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
    Column("term", Text, nullable=False),
    Column("term_year", SmallInteger),
    Column("term_season", Text),
    Column("section", Text),
    Column("campus", Text),
    Column("level", Text),
    Column("source_file", Text),
    Column("grade_a", Integer),
    Column("grade_b", Integer),
    Column("grade_c", Integer),
    Column("grade_d", Integer),
    Column("grade_f", Integer),
    Column("grade_q", Integer),
    Column("grade_i", Integer),
    Column("grade_s", Integer),
    Column("grade_u", Integer),
    Column("grade_x", Integer),
    Column("af_total", Integer),
    Column("enrolled", Integer),
    Column("gpa", Numeric(4, 3)),
    Column("source_row", Integer),
)

rmp_professors = Table(
    "rmp_professors",
    metadata,
    Column("rmp_id", BigInteger, primary_key=True),
    Column("node_id", Text),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("full_name", Text),
    Column("department", Text),
    Column("school_id", Text),
    Column("avg_rating", Numeric(4, 2)),
    Column("avg_difficulty", Numeric(4, 2)),
    Column("num_ratings", Integer, nullable=False, server_default="0"),
    Column("would_take_again_percent", Numeric(5, 2)),
    Column("ratings_distribution", JSONB),
    Column("course_codes", JSONB),
    Column("rmp_url", Text),
    Column("reviews_window_start", DateTime(timezone=True)),
    Column("reviews_window_end", DateTime(timezone=True)),
    Column("fetched_at", DateTime(timezone=True), server_default=func.now()),
    Column("details_fetched_at", DateTime(timezone=True)),
)

rmp_ratings = Table(
    "rmp_ratings",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "rmp_id",
        BigInteger,
        ForeignKey("rmp_professors.rmp_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rmp_rating_id", BigInteger),
    Column("course_id", BigInteger, ForeignKey("courses.id", ondelete="SET NULL")),
    Column("class_code", Text),
    Column("comment", Text),
    Column("helpful", Numeric(4, 2)),
    Column("clarity", Numeric(4, 2)),
    Column("difficulty", Numeric(4, 2)),
    Column("rated_at", DateTime(timezone=True)),
    Column("is_online", Boolean),
    Column("attendance_mandatory", Boolean),
    Column("textbook_use", Text),
    Column("is_for_credit", Boolean),
    Column("grade", Text),
    Column("would_take_again", Boolean),
    Column("rating_tags", Text),
    Column("thumbs_up", Integer),
    Column("thumbs_down", Integer),
    Column("course_match_status", Text),
    Column("raw", JSONB, nullable=False, server_default="{}"),
)

summaries = Table(
    "summaries",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("subject_type", Text, nullable=False),
    Column(
        "instructor_id",
        BigInteger,
        ForeignKey("instructors.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("course_id", BigInteger, ForeignKey("courses.id", ondelete="CASCADE")),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("window_start", DateTime(timezone=True)),
    Column("window_end", DateTime(timezone=True)),
    Column("summary_md", Text, nullable=False),
    Column("facets", JSONB, nullable=False, server_default="{}"),
    Column("source_rating_count", Integer, nullable=False, server_default="0"),
    Column("generated_at", DateTime(timezone=True), server_default=func.now()),
)

sections = Table(
    "sections",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("course_id", BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
    Column("instructor_id", BigInteger, ForeignKey("instructors.id", ondelete="SET NULL")),
    Column("term", Text, nullable=False),
    Column("section_code", Text, nullable=False),
    Column("campus", Text),
    Column("delivery", Text),
    Column("honors", Boolean, nullable=False, server_default="false"),
    Column("meets", JSONB, nullable=False, server_default="[]"),
    Column("seats", Integer),
    Column("seats_open", Integer),
)

name_links = Table(
    "name_links",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("source", Text, nullable=False, server_default="grades_csv"),
    Column("source_name", Text, nullable=False),
    Column("normalized_name", Text, nullable=False),
    Column("instructor_id", BigInteger, ForeignKey("instructors.id", ondelete="CASCADE")),
    Column("rmp_id", BigInteger),
    Column("method", Text, nullable=False),
    Column("confidence", Numeric(5, 2), nullable=False),
    Column("linked_at", DateTime(timezone=True), server_default=func.now()),
)

instructor_traits = Table(
    "instructor_traits",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "instructor_id",
        BigInteger,
        ForeignKey("instructors.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("course_id", BigInteger, ForeignKey("courses.id", ondelete="SET NULL")),
    Column("lots_of_quizzes", Numeric(4, 3)),
    Column("exam_difficulty", Numeric(4, 3)),
    Column("lecture_quality", Numeric(4, 3)),
    Column("attendance_taken", Numeric(4, 3)),
    Column("extra_credit", Numeric(4, 3)),
    Column("heavy_workload", Numeric(4, 3)),
    Column("grades_generously", Numeric(4, 3)),
    Column("confidence", Numeric(4, 3)),
    Column("model", Text, nullable=False),
    Column("question_version", Text, nullable=False),
    Column("review_count", Integer, nullable=False, server_default="0"),
    Column("answers", JSONB, nullable=False, server_default="{}"),
    Column("decided_at", DateTime(timezone=True), server_default=func.now()),
)
