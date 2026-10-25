"""The loaders for the project's own data pipeline output.

Fixtures mirror the real files on the data branch: Data/courses.csv and
Data/output/schedule_dataset.csv, including the review JSON blobs.
"""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from app.ingest.load_catalog import parse_row as parse_catalog_row
from app.ingest.load_rmp_dataset import Stats, extract

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "catalog_sample.csv"
DATASET = FIXTURES / "schedule_dataset_sample.csv"


def catalog_rows() -> list[dict]:
    import csv

    with CATALOG.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_catalog_row_carries_the_prerequisite_text():
    """The planning doc's "Prereqs" requirement comes straight from here."""
    record = parse_catalog_row(catalog_rows()[0])

    assert record is not None
    assert (record["dept"], record["number"]) == ("CSCE", "121")
    assert record["title"] == "Introduction to Program Design and Concepts"
    assert record["credits"] == "3"
    assert record["prereq_text"] == "MATH 151 or concurrent enrollment."
    assert record["is_honors_dept"] is False


def test_catalog_honors_department_flag_and_coreq():
    record = parse_catalog_row(catalog_rows()[1])
    assert record is not None
    assert record["is_honors_dept"] is True
    assert record["coreq_text"] == "MATH 151 recitation"


def test_a_catalog_row_with_no_course_code_is_skipped():
    assert parse_catalog_row(catalog_rows()[2]) is None


def extracted():
    return extract(DATASET, limit=None, stats=Stats())


def test_professor_aggregates_are_read_from_the_dataset():
    data = extracted()
    assert set(data.professors) == {1001}

    professor = data.professors[1001]
    assert professor["full_name"] == "Jane Doe"
    assert (professor["first_name"], professor["last_name"]) == ("Jane", "Doe")
    assert professor["avg_rating"] == 4.6
    assert professor["num_ratings"] == 80
    assert professor["would_take_again_percent"] == 83.0
    assert professor["rmp_url"].endswith("/1001")
    assert professor["reviews_window_start"].tzinfo is timezone.utc


def test_reviews_are_deduplicated_by_their_own_id():
    """Review 9001 appears in both the overall and the course-specific blob."""
    data = extracted()
    assert set(data.reviews) == {9001, 9002}


def test_the_course_scoped_copy_of_a_review_wins():
    """It is the copy that says which course the review is about."""
    data = extracted()
    assert data.reviews[9001]["_course_key"] == ("CSCE", "121")
    assert data.reviews[9002]["_course_key"] is None


def test_the_richer_review_fields_survive():
    data = extracted()
    review = data.reviews[9001]

    assert review["grade"] == "A"
    assert review["would_take_again"] is True
    assert review["rating_tags"] == "Caring--Clear grading criteria"
    assert review["attendance_mandatory"] is True
    assert review["is_online"] is False
    assert review["thumbs_up"] == 2
    assert review["course_match_status"] == "matched"
    assert review["rated_at"].year == 2026


def test_a_negative_would_take_again_answer_is_false_not_missing():
    data = extracted()
    assert data.reviews[9002]["would_take_again"] is False
    assert data.reviews[9002]["is_online"] is True


def test_pipeline_matches_are_taken_as_given():
    data = extracted()
    assert data.pipeline_links == {"DOE J": (1001, 97.5)}


def test_unmatched_rows_contribute_a_name_but_no_link():
    data = extracted()
    assert data.instructor_names == {"DOE J", "RODRIGUEZ C", "NOBODY Z"}
    assert "RODRIGUEZ C" not in data.pipeline_links


def test_the_roster_is_built_from_matched_rows():
    data = extracted()
    assert data.roster == {"Jane Doe": 1001}


def test_limit_stops_reading_early():
    stats = Stats()
    extract(DATASET, limit=1, stats=stats)
    assert stats.rows_read == 1
