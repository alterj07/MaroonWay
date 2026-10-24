"""Row -> payload shaping, including the weighted composite."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.presenters import course_instructor, course_score, professor_payload, score_block
from app.scoring import ScoreWeights

WEIGHTS = ScoreWeights(rating=1.0, would_take_again=0.3, gpa=0.4, difficulty=-0.5)

# Postgres hands numerics back as Decimal; every payload field must be JSON-safe.
ROW = {
    "instructor_id": 7,
    "full_name": "Jane Doe",
    "department": "Computer Science",
    "rmp_id": 200147,
    "rating_count": 12,
    "raw_rating": Decimal("4.50"),
    "raw_difficulty": Decimal("3.20"),
    "would_take_again_percent": Decimal("83.00"),
    "adj_rating": Decimal("4.0455"),
    "adj_difficulty": Decimal("3.1000"),
    "adj_would_take_again": Decimal("3.7045"),
    "adj_gpa": Decimal("3.9000"),
}


def test_score_block_converts_decimals_and_adds_the_composite():
    block = score_block(ROW, WEIGHTS)
    assert isinstance(block["adj_rating"], float)
    assert block["rating_count"] == 12
    assert block["composite"] == pytest.approx(
        4.0455 + 0.3 * 3.7045 - 0.5 * 3.1 + 0.4 * 3.9, abs=1e-6
    )


def test_score_block_tolerates_missing_optional_scores():
    block = score_block({**ROW, "adj_would_take_again": None, "adj_gpa": None}, WEIGHTS)
    assert block["adj_gpa"] is None
    assert block["composite"] == pytest.approx(4.0455 - 0.5 * 3.1, abs=1e-6)


def test_course_score_carries_class_specific_counts():
    row = {
        "course_id": 3,
        "code": "CSCE121",
        "title": "Intro to Program Design",
        "campus": "CSTAT",
        "honors": False,
        "class_rating_count": 4,
        "section_count": 2,
        "adj_rating": Decimal("4.2"),
        "adj_difficulty": Decimal("3.4"),
        "adj_would_take_again": None,
        "adj_gpa": Decimal("3.1"),
    }
    payload = course_score(row, WEIGHTS)
    assert payload["code"] == "CSCE121"
    assert payload["class_rating_count"] == 4
    assert isinstance(payload["composite"], float)


def test_course_instructor_reports_both_rating_counts():
    row = {
        "instructor_id": 7,
        "full_name": "Jane Doe",
        "department": "CS",
        "rmp_id": 1,
        "class_rating_count": 0,
        "instructor_rating_count": 12,
        "section_count": 1,
        "adj_rating": Decimal("4.0"),
        "adj_difficulty": Decimal("3.0"),
        "adj_would_take_again": None,
        "adj_gpa": None,
    }
    payload = course_instructor(row, WEIGHTS)
    assert payload["class_rating_count"] == 0
    assert payload["instructor_rating_count"] == 12, (
        "a class with no reviews of its own still shows the professor's evidence"
    )


def test_professor_payload_nests_and_keeps_every_section():
    raw = {
        **ROW,
        "courses": [
            {
                "course_id": 3,
                "code": "CSCE121",
                "title": "Intro",
                "campus": "CSTAT",
                "honors": False,
                "class_rating_count": 4,
                "section_count": 2,
                "adj_rating": Decimal("4.2"),
                "adj_difficulty": Decimal("3.4"),
                "adj_would_take_again": None,
                "adj_gpa": Decimal("3.1"),
            }
        ],
        "grades": [
            {
                "code": "CSCE121",
                "title": "Intro",
                "term": "202531",
                "term_year": 2025,
                "term_season": "fall",
                "section": "501",
                "gpa": Decimal("3.102"),
                "enrolled": 67,
            }
        ],
        "recent_comments": [
            {
                "class_code": "CSCE121",
                "comment": "Tough but fair.",
                "helpful": Decimal("5"),
                "clarity": Decimal("4"),
                "difficulty": Decimal("3"),
                "rated_at": None,
            }
        ],
        "summaries": [{"subject_type": "instructor", "summary_md": "..."}],
    }
    payload = professor_payload(raw, WEIGHTS)

    assert payload["instructor_id"] == 7
    assert payload["score"]["rating_count"] == 12
    assert payload["courses"][0]["code"] == "CSCE121"
    assert payload["grades"][0]["gpa"] == pytest.approx(3.102)
    assert payload["recent_comments"][0]["helpful"] == 5.0
    assert payload["summaries"][0]["subject_type"] == "instructor"


def test_professor_payload_works_with_nothing_attached():
    payload = professor_payload(ROW, WEIGHTS)
    assert payload["courses"] == []
    assert payload["grades"] == []
    assert payload["recent_comments"] == []
    assert payload["summaries"] == []
