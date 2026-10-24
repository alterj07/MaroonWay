"""Response shapes. Pydantic coerces the numerics Postgres hands back."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ScoreOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rating_count: int = 0
    raw_rating: float | None = None
    raw_difficulty: float | None = None
    would_take_again_percent: float | None = None
    adj_rating: float
    adj_difficulty: float
    adj_would_take_again: float | None = None
    adj_gpa: float | None = None
    composite: float


class CourseScoreOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    course_id: int
    code: str
    title: str | None = None
    campus: str | None = None
    honors: bool = False
    class_rating_count: int = 0
    section_count: int = 0
    adj_rating: float
    adj_difficulty: float
    adj_would_take_again: float | None = None
    adj_gpa: float | None = None
    composite: float


class GradeRowOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    title: str | None = None
    term: str
    term_year: int | None = None
    term_season: str | None = None
    section: str | None = None
    gpa: float | None = None
    enrolled: int | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    class_code: str | None = None
    comment: str
    helpful: float | None = None
    clarity: float | None = None
    difficulty: float | None = None
    rated_at: datetime | None = None


class SummaryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject_type: str
    course_id: int | None = None
    course_code: str | None = None
    model: str
    prompt_version: str
    summary_md: str
    facets: dict[str, Any] = {}
    window_start: datetime | None = None
    window_end: datetime | None = None
    source_rating_count: int = 0
    generated_at: datetime | None = None


class ProfessorOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instructor_id: int
    full_name: str
    department: str | None = None
    rmp_id: int | None = None
    score: ScoreOut
    courses: list[CourseScoreOut] = []
    grades: list[GradeRowOut] = []
    recent_comments: list[CommentOut] = []
    summaries: list[SummaryOut] = []


class SearchHitOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instructor_id: int
    full_name: str
    department: str | None = None
    rmp_id: int | None = None
    name_similarity: float | None = None
    score: ScoreOut


class SearchOut(BaseModel):
    query: str
    department: str | None = None
    total: int
    limit: int
    offset: int
    results: list[SearchHitOut]


class CourseInstructorOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instructor_id: int
    full_name: str
    department: str | None = None
    rmp_id: int | None = None
    class_rating_count: int = 0
    instructor_rating_count: int = 0
    section_count: int = 0
    adj_rating: float
    adj_difficulty: float
    adj_would_take_again: float | None = None
    adj_gpa: float | None = None
    composite: float


class SummaryEnvelopeOut(BaseModel):
    """Summaries are batch-generated, so "not yet" is a normal answer."""

    status: str  # "ready" | "missing"
    instructor_id: int
    course_code: str | None = None
    prompt_version: str
    summary: SummaryOut | None = None


class HealthOut(BaseModel):
    status: str
    database: str
    data_version: int
    detail: str | None = None
