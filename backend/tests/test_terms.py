"""Semester arithmetic for the "past 2 semesters" window."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.terms import FALL, SPRING, SUMMER, Term, parse_term, recent_terms, term_of, window_of


def utc(year: int, month: int, day: int = 15) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_months_map_to_semesters():
    assert term_of(utc(2025, 2)).season == SPRING
    assert term_of(utc(2025, 6)).season == SUMMER
    assert term_of(utc(2025, 10)).season == FALL


def test_terms_order_within_and_across_years():
    assert Term(2025, SPRING) < Term(2025, SUMMER) < Term(2025, FALL) < Term(2026, SPRING)


def test_previous_crosses_the_year_boundary():
    assert Term(2026, SPRING).previous() == Term(2025, FALL)
    assert Term(2025, FALL).previous() == Term(2025, SUMMER)


def test_recent_terms_come_from_the_data_not_today():
    dates = [utc(2024, 9), utc(2025, 2), utc(2025, 10), utc(2019, 3)]
    assert recent_terms(dates, 2) == [Term(2025, FALL), Term(2025, SPRING)]


def test_recent_terms_tolerates_an_empty_history():
    assert recent_terms([], 2) == []
    assert window_of([]) is None


def test_window_spans_the_given_terms():
    start, end = window_of([Term(2025, SPRING), Term(2025, FALL)])
    assert start == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_a_review_inside_the_window_is_inside_the_bounds():
    start, end = Term(2025, FALL).bounds()
    assert start <= utc(2025, 9) < end
    assert not (start <= utc(2025, 5) < end)


def test_parse_numeric_term_codes():
    assert parse_term(202531) == Term(2025, FALL)
    assert parse_term("202510") == Term(2025, SPRING)
    assert parse_term("202520") == Term(2025, SUMMER)


def test_parse_written_terms():
    assert parse_term("Fall 2025") == Term(2025, FALL)
    assert parse_term("2025 SPRING") == Term(2025, SPRING)
    assert parse_term("FA25") == Term(2025, FALL)


def test_unparseable_terms_are_none_not_a_guess():
    assert parse_term(None) is None
    assert parse_term("") is None
    assert parse_term("whenever") is None


def test_labels_read_like_a_human_wrote_them():
    assert Term(2025, FALL).label == "Fall 2025"
