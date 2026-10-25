"""The one place that knows what the grades CSV's columns are called.

Phase 0 of the plan: run ``python -m app.ingest.profile_csv <file>``, read what
it prints, and if a column did not map, add it to ``OVERRIDES`` below. Every
other ingest step reads this module, so a renamed column is a one-line change
here rather than a hunt through loaders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Fill in after profiling the real file: {"our_field": "Exact CSV Header"}.
#: Takes precedence over the alias guesses below.
OVERRIDES: dict[str, str] = {}

#: Candidate spellings per field, as normalised header text (see norm_header).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "term": ("term", "semester", "term_code", "termcode", "year_semester", "yearterm"),
    # "subject" outranks "department" deliberately: A&M's grade reports carry
    # both, where subject is the course prefix ("ASCC") and department is the
    # administrative unit ("TASP/TSI ADMINISTRATION").
    "dept": ("subject", "dept", "subject_code", "prefix", "course_prefix", "department"),
    "number": ("number", "course_number", "course_no", "catalog_number", "catalog_nbr", "nbr"),
    "course_code": ("course", "course_code", "class", "class_code", "course_id"),
    "title": ("title", "course_title", "course_name", "class_title"),
    "section": ("section", "section_number", "sect", "section_code", "crn"),
    "instructor": (
        "instructor",
        "teacher",
        "professor",
        "instructor_name",
        "prof",
        "primary_instructor",
    ),
    "gpa": ("gpa", "average_gpa", "avg_gpa", "gpa_average", "average_gpa_4_0"),
    "enrolled": ("enrolled", "total", "students", "count", "headcount", "total_students"),
    "grade_a": ("a", "grade_a", "a_count", "num_a", "as"),
    "grade_b": ("b", "grade_b", "b_count", "num_b", "bs"),
    "grade_c": ("c", "grade_c", "c_count", "num_c", "cs"),
    "grade_d": ("d", "grade_d", "d_count", "num_d", "ds"),
    "grade_f": ("f", "grade_f", "f_count", "num_f", "fs"),
    "grade_q": ("q", "grade_q", "q_count", "q_drop", "q_drops", "w", "withdrawn"),
    "grade_i": ("i", "grade_i", "incomplete"),
    "grade_s": ("s", "grade_s", "satisfactory"),
    "grade_u": ("u", "grade_u", "unsatisfactory"),
    "grade_x": ("x", "grade_x"),
    "af_total": ("af_total", "af", "a_f_total"),
    "level": ("level", "course_level", "career"),
    "source_file": ("file", "source_file", "report_file"),
    # Not "college": in A&M's reports that is the academic college
    # ("CENTER FOR ACAD ENHANCEMENT"), not a campus.
    "campus": ("campus", "campus_basis", "location", "site"),
    "honors": ("honors", "honor", "is_honors"),
    # Scheduling fields. Whether these exist is the open question from planning:
    # if the profiler finds them, sections can be loaded for real; if not, the
    # scheduler runs on tests/fixtures until a sections file arrives.
    "days": ("days", "meeting_days", "day", "days_met", "pattern"),
    "start_time": ("start", "start_time", "begin_time", "begins", "time_start"),
    "end_time": ("end", "end_time", "ends", "time_end"),
    "building": ("building", "bldg", "building_code"),
    "room": ("room", "room_number", "rm"),
    "delivery": ("delivery", "instruction_mode", "mode", "method", "format"),
}

#: Without these, grades cannot be loaded at all.
REQUIRED_FIELDS = ("dept", "number", "instructor", "term")
#: At least one of these makes a row worth storing.
VALUE_FIELDS = ("gpa", "grade_a", "grade_b", "grade_c", "grade_d", "grade_f")
#: Presence of these decides whether Phase 4 has real data.
SCHEDULE_FIELDS = ("days", "start_time", "end_time", "building", "room", "delivery")


def norm_header(header: str) -> str:
    """``"Avg GPA (4.0)"`` -> ``"avg_gpa_4_0"``."""
    return _NON_ALNUM.sub("_", header.strip().lower()).strip("_")


@dataclass(slots=True)
class ColumnMap:
    """Which CSV header feeds each of our fields."""

    fields: dict[str, str] = field(default_factory=dict)
    unmapped_headers: list[str] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)

    @property
    def missing_required(self) -> list[str]:
        have = set(self.fields)
        missing = [f for f in REQUIRED_FIELDS if f not in have]
        # dept + number can arrive as one "CSCE 121" column instead.
        if "course_code" in have:
            missing = [f for f in missing if f not in ("dept", "number")]
        return missing

    @property
    def has_values(self) -> bool:
        return any(f in self.fields for f in VALUE_FIELDS)

    @property
    def schedule_fields(self) -> list[str]:
        return [f for f in SCHEDULE_FIELDS if f in self.fields]

    def get(self, row: dict[str, str], field_name: str) -> str | None:
        header = self.fields.get(field_name)
        if header is None:
            return None
        value = row.get(header)
        if value is None:
            return None
        value = value.strip()
        return value or None


def resolve_columns(headers: list[str]) -> ColumnMap:
    """Map our field names onto the file's real headers."""
    normalised = {norm_header(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}

    for our_field, header in OVERRIDES.items():
        if header in headers:
            mapping[our_field] = header

    for our_field, aliases in FIELD_ALIASES.items():
        if our_field in mapping:
            continue
        hits = [normalised[alias] for alias in aliases if alias in normalised]
        if not hits:
            continue
        mapping[our_field] = hits[0]
        if len(hits) > 1:
            ambiguous[our_field] = hits

    used = set(mapping.values())
    return ColumnMap(
        fields=mapping,
        unmapped_headers=[h for h in headers if h and h not in used],
        ambiguous=ambiguous,
    )


COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]{2,5})\s*[-_ ]?\s*(\d{3}[A-Za-z]?)\s*$")


def split_course_code(value: str | None) -> tuple[str, str] | None:
    """``"CSCE 121"`` / ``"csce-121"`` -> ``("CSCE", "121")``."""
    if not value:
        return None
    match = COURSE_CODE_RE.match(value)
    if not match:
        return None
    return match.group(1).upper(), match.group(2).upper()
