"""Response shapes. Pydantic coerces the numerics Postgres hands back."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


# --- scheduling ---------------------------------------------------------------


class MeetingOut(BaseModel):
    day: str
    start: str
    end: str
    building: str | None = None
    room: str | None = None


class ScheduleSectionOut(BaseModel):
    section_id: int
    course_id: int
    code: str
    section_code: str
    instructor_id: int | None = None
    instructor_name: str | None = None
    campus: str | None = None
    delivery: str | None = None
    honors: bool = False
    seats_open: int | None = None
    meetings: list[MeetingOut] = []
    adj_rating: float | None = None
    adj_difficulty: float | None = None
    adj_gpa: float | None = None
    #: Share of students who earned an A, 0-1.
    pct_a: float | None
    #: Reviews behind the rating, and other sections at these exact times with
    #: a different instructor.
    class_reviews: int = 0
    professor_reviews: int = 0
    same_time_alternatives: int = 0


class PreferencesOut(BaseModel):
    """The weights a request was ranked with, and where they came from."""

    rating: float
    difficulty: float
    grades: float
    workload: float
    lecture: float
    attendance: float
    avoid_early_mornings: float
    avoid_fridays: float
    #: "spread" | "compact" | None.
    day_shape: str | None = None
    delivery: str | None = None
    campus: str | None = None
    honors: bool | None = None
    min_gap_minutes: int
    #: "jev-1.14" when Jev decided, "heuristic" for the keyword fallback,
    #: "default" when the student expressed nothing.
    engine: str
    #: Questions Jev answered below its confidence floor.
    low_confidence: list[str] = []
    stated: str | None = None


class ContributionOut(BaseModel):
    name: str
    weight: float
    value: float
    points: float


class ScheduleOut(BaseModel):
    sections: list[ScheduleSectionOut]
    #: 0-1 against the stated preferences; 0 when none were expressed.
    preference_score: float = 0.0
    #: What earned this schedule its place, for the UI to show.
    reasons: list[str] = []
    #: An earlier option has this exact timetable; only the staff differ.
    same_shape: bool = False
    contributions: list[ContributionOut] = []
    #: Minutes between the two closest classes. Null when nothing shares a day.
    tightest_gap: int | None = None
    mean_rating: float
    mean_difficulty: float
    mean_gpa: float | None = None
    mean_pct_a: float | None = None
    earliest_start: str | None = None
    days_on_campus: int
    #: Minutes spent waiting between classes, summed over the week.
    idle_minutes: int


class ScheduleRequest(BaseModel):
    """What the student is asking for."""

    model_config = ConfigDict(extra="forbid")

    term: str
    #: Course codes, e.g. ["CSCE121", "MATH151"].
    courses: list[str] = Field(min_length=1, max_length=10)
    #: What the student wants, in their own words. Jev turns this into the
    #: weights that rank the results.
    wants: str | None = Field(default=None, max_length=2000)
    #: The doc's floor is 20 minutes. None means "whatever Jev infers, or 20";
    #: an explicit value always wins.
    min_gap_minutes: int | None = Field(default=None, ge=0, le=240)
    earliest: str | None = Field(default=None, description='e.g. "09:00"')
    latest: str | None = Field(default=None, description='e.g. "17:00"')
    excluded_days: list[str] = []
    campus: str | None = None
    honors: bool | None = None
    delivery: str | None = Field(default=None, description="F2F, WEB or HYBRID")
    open_only: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class ScheduleResponse(BaseModel):
    request: ScheduleRequest
    count: int
    schedules: list[ScheduleOut]
    preferences: PreferencesOut
    #: Set when nothing could be built, explaining which constraint bit.
    detail: str | None = None
    #: Preferences the timetable could not honour, so the student is told
    #: rather than left wondering why Friday classes came back anyway.
    relaxed: list[str] = Field(default_factory=list)


class PreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wants: str = Field(min_length=1, max_length=2000)


class PreferenceResponse(BaseModel):
    preferences: PreferencesOut
    #: Every question Jev was asked and what it answered, so the UI can show
    #: the student what was understood before building anything.
    answers: dict[str, Any] = {}


# --- importing sections from a browser session --------------------------------


class ImportedMeeting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: "MWF", "TR", "Mon,Wed" or a list -- parsed server-side.
    days: str | list[str] | None = None
    start: str | None = None
    end: str | None = None
    building: str | None = None
    room: str | None = None


class ImportedSection(BaseModel):
    """One section as a browser scraped it. Deliberately forgiving: the point
    is to accept whatever the page gives and normalise here."""

    model_config = ConfigDict(extra="ignore")

    term: str
    subject: str | None = None
    number: str | None = None
    #: "CSCE 121" as an alternative to subject + number.
    course: str | None = None
    section: str
    instructor: str | None = None
    campus: str | None = None
    delivery: str | None = None
    honors: bool | None = None
    seats: int | None = None
    seats_open: int | None = None
    meetings: list[ImportedMeeting] = []


class SectionImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[ImportedSection] = Field(min_length=1, max_length=5000)
    #: True reports what would happen and writes nothing.
    dry_run: bool = False


class SectionImportResponse(BaseModel):
    received: int
    accepted: int
    sections_written: int
    meetings: int
    skipped: dict[str, int] = {}
    unknown_courses: list[str] = []
    unknown_instructors: list[str] = []
    dry_run: bool = False


# --- students -----------------------------------------------------------------


class StudentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    subject: str
    email: str
    name: str | None = None


class StudentPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wants: str | None = Field(default=None, max_length=2000)
    weights: dict[str, Any] = {}
    engine: str | None = None
    courses: list[str] = Field(default_factory=list, max_length=20)
    term: str | None = None


class StudentPreferencesOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wants: str | None = None
    weights: dict[str, Any] = {}
    engine: str | None = None
    courses: list[str] = []
    term: str | None = None
    updated_at: datetime | None = None


class SaveScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    label: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any]


class SavedScheduleOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    term: str
    label: str | None = None
    payload: dict[str, Any]
    created_at: datetime | None = None
