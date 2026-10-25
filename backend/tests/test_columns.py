"""Column mapping and row parsing for the grades CSV.

Phase 0 of the plan is "read the real file first", so these run against fixtures
shaped like an A&M grade-distribution export rather than the real one -- the
point is that a different header spelling is a one-line change in
app/ingest/columns.py, not a change here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest import columns as columns_module
from app.ingest.columns import norm_header, resolve_columns, split_course_code
from app.ingest.load_grades import normalize_campus, parse_row, read_rows
from app.ingest.profile_csv import main as profile_main

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "grades_sample.csv"
COMBINED = FIXTURES / "grades_combined_code.csv"


def test_header_normalisation():
    assert norm_header("Average GPA") == "average_gpa"
    assert norm_header("  Avg GPA (4.0) ") == "avg_gpa_4_0"
    assert norm_header("A") == "a"


def test_realistic_headers_map_onto_our_fields():
    headers, _ = read_rows(SAMPLE, None)
    cmap = resolve_columns(headers)

    assert cmap.fields["term"] == "Term"
    assert cmap.fields["dept"] == "Subject"
    assert cmap.fields["number"] == "Course Number"
    assert cmap.fields["instructor"] == "Instructor"
    assert cmap.fields["gpa"] == "Average GPA"
    assert cmap.fields["grade_a"] == "A"
    assert cmap.fields["grade_q"] == "Q"
    assert cmap.fields["title"] == "Course Title"
    assert cmap.fields["campus"] == "Campus"
    assert cmap.missing_required == []
    assert cmap.has_values


def test_this_file_carries_no_meeting_times():
    """The question planning left open, answered per file rather than assumed."""
    headers, _ = read_rows(SAMPLE, None)
    assert resolve_columns(headers).schedule_fields == []


def test_a_combined_course_column_satisfies_dept_and_number():
    headers, _ = read_rows(COMBINED, None)
    cmap = resolve_columns(headers)

    assert "dept" not in cmap.fields
    assert cmap.fields["course_code"] == "Course"
    assert cmap.missing_required == [], "dept+number can arrive as one column"


def test_overrides_beat_the_alias_guesses(monkeypatch):
    monkeypatch.setitem(columns_module.OVERRIDES, "gpa", "Course Title")
    cmap = resolve_columns(["Average GPA", "Course Title"])
    assert cmap.fields["gpa"] == "Course Title"


def test_unmapped_columns_are_reported_not_silently_dropped():
    cmap = resolve_columns(["Subject", "Course Number", "Instructor", "Term", "Weird Column"])
    assert cmap.unmapped_headers == ["Weird Column"]


def test_split_course_code_variants():
    assert split_course_code("CSCE 121") == ("CSCE", "121")
    assert split_course_code("csce-121") == ("CSCE", "121")
    assert split_course_code("MATH151") == ("MATH", "151")
    assert split_course_code("BIOL 111H") == ("BIOL", "111H")
    assert split_course_code("not a course") is None
    assert split_course_code(None) is None


def test_campus_normalisation():
    assert normalize_campus("College Station") == "CSTAT"
    assert normalize_campus("COLLEGE STATION") == "CSTAT"
    assert normalize_campus("Blinn") == "BLINN"
    assert normalize_campus(None) is None
    assert normalize_campus("") is None
    assert normalize_campus("Unknown") is None


def test_galveston_and_qatar_are_their_own_campuses():
    """They are A&M campuses in their own right and the grade data covers
    both; dropping them mis-filed about 1,200 instructor-courses."""
    assert normalize_campus("Galveston") == "GALV"
    assert normalize_campus("Qatar") == "QATAR"
    # A phrase beats an abbreviation, so this is Galveston and not CSTAT.
    assert normalize_campus("TAMU Galveston") == "GALV"


def test_campus_abbreviation_matches_a_word_not_a_substring():
    """"cs" lives inside "PHYSICS", and campus is aliased to columns such as
    campus_basis that can hold a department name."""
    assert normalize_campus("PHYSICS") is None
    assert normalize_campus("ECONOMICS") is None
    assert normalize_campus("CS") == "CSTAT"


def parsed_rows(path: Path):
    headers, rows = read_rows(path, None)
    cmap = resolve_columns(headers)
    return [parse_row(row, cmap, i) for i, row in enumerate(rows, start=1)]


def test_a_good_row_parses_completely():
    record, reason = parsed_rows(SAMPLE)[0]
    assert reason == ""
    assert record is not None
    assert (record.dept, record.number, record.section) == ("CSCE", "121", "501")
    assert record.instructor == "DOE, JANE M"
    assert record.gpa == pytest.approx(3.102)
    assert record.term == "202531"
    assert (record.term_year, record.term_season) == (2025, "fall")
    assert record.campus == "CSTAT"
    assert record.honors is False
    assert record.grades["grade_a"] == 30
    assert record.enrolled == 67, "enrolment is summed from grade counts when absent"


def test_rows_without_an_instructor_are_skipped_with_a_reason():
    record, reason = parsed_rows(SAMPLE)[4]
    assert record is None
    assert reason == "no_instructor"


def test_rows_with_neither_gpa_nor_grades_are_skipped():
    record, reason = parsed_rows(SAMPLE)[5]
    assert record is None
    assert reason == "no_values"


def test_blinn_rows_keep_their_campus():
    record, _ = parsed_rows(SAMPLE)[3]
    assert record is not None and record.campus == "BLINN"


def test_a_combined_code_row_parses_into_dept_and_number():
    record, reason = parsed_rows(COMBINED)[1]
    assert reason == ""
    assert record is not None
    assert (record.dept, record.number) == ("MATH", "151")
    assert record.enrolled == 120
    assert (record.term_year, record.term_season) == (2025, "fall")


def test_profiler_runs_read_only_and_reports_the_mapping(capsys):
    assert profile_main([str(SAMPLE)]) == 0
    out = capsys.readouterr().out

    assert "mapped fields" in out
    assert "gpa          <- Average GPA" in out
    assert "grades-only" in out, "it must say whether meeting times exist"
    assert "MISSING REQUIRED" not in out


def test_profiler_rejects_a_missing_file(capsys):
    assert profile_main(["/nonexistent/grades.csv"]) == 1
