"""Normalising the scraper's output.

The fixtures below mirror the real ``Professor`` / ``Professor_Gist`` objects in
RateMyProfessor_Database_APIs 1.1.1, read from the installed package: a base64
node id in ``id``, the numeric one in ``legacy_id``, and per-review dicts keyed
``helpfulRating`` / ``clarityRating`` / ``difficultyRating`` / ``class`` /
``date`` / ``attendanceMandatory`` / ``isForOnlineClass``.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from app.services.rmp import (
    decode_node_id,
    normalize_professor,
    normalize_rating,
    parse_rmp_date,
    to_jsonable,
)

NODE_ID = base64.b64encode(b"Teacher-200147").decode()


class FakeGist:
    """What fetch_all_professors_from_a_school returns."""

    def __init__(self, **kwargs):
        self.avg_difficulty = kwargs.get("avg_difficulty", 3.0)
        self.avg_rating = kwargs.get("avg_rating", 4.0)
        self.department = "Computer Science"
        self.first_name = "Jane"
        self.id = kwargs.get("id", NODE_ID)
        self.is_saved = False
        self.last_name = "Doe"
        self.legacy_id = kwargs.get("legacy_id", 200147)
        self.num_ratings = kwargs.get("num_ratings", 12)
        self.school = {"legacyId": 1003, "name": "Texas A&M University"}
        self.would_take_again_percent = kwargs.get("would_take_again_percent", 83.0)


class FakeProfessor(FakeGist):
    """What fetch_a_professor returns -- the gist plus ratings."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ratings_distribution = {"r1": 1, "r5": 6, "total": 12}
        self.course_codes = [{"courseName": "CSCE121", "courseCount": 9}]
        self.related_teachers = []
        self.department_id = "abc"
        self.lock_status = "unlocked"
        self.is_prof_current_user = False
        self.ratings = kwargs.get(
            "ratings",
            [
                {
                    "comment": "Tough but fair.",
                    "flagStatus": "UNFLAGGED",
                    "createdByUser": False,
                    "date": "2025-09-01 12:00:00 +0000 UTC",
                    "class": "csce 121",
                    "helpfulRating": 5,
                    "clarityRating": 4,
                    "isForOnlineClass": False,
                    "difficultyRating": 3,
                    "attendanceMandatory": "mandatory",
                    "textbookUse": "No",
                    "isForCredit": True,
                }
            ],
        )


def test_legacy_id_wins_over_the_base64_node_id():
    """dir() puts `id` before `legacy_id`; alias order has to beat that."""
    record = normalize_professor(FakeGist())
    assert record is not None
    assert record.rmp_id == 200147
    assert record.node_id == NODE_ID


def test_node_id_decodes_when_there_is_no_legacy_id():
    assert decode_node_id(NODE_ID) == 200147
    record = normalize_professor(FakeGist(legacy_id=None))
    assert record is not None and record.rmp_id == 200147


def test_a_payload_with_no_recoverable_id_is_dropped():
    assert normalize_professor(FakeGist(legacy_id=None, id="not-base64!!")) is None
    assert decode_node_id("not-base64!!") is None


def test_unrated_professors_report_no_data_rather_than_zero():
    """The listing writes 0.0 for unrated professors; feeding that to the
    scoring prior would claim they were rated terribly."""
    record = normalize_professor(
        FakeGist(num_ratings=0, avg_rating=0.0, avg_difficulty=0.0, would_take_again_percent=-1)
    )
    assert record is not None
    assert record.avg_rating is None
    assert record.avg_difficulty is None
    assert record.would_take_again_percent is None


def test_would_take_again_minus_one_means_nobody_answered():
    record = normalize_professor(FakeGist(would_take_again_percent=-1))
    assert record is not None and record.would_take_again_percent is None


def test_school_id_is_read_out_of_the_nested_dict():
    record = normalize_professor(FakeGist())
    assert record is not None and record.school_id == "1003"


def test_ratings_are_normalised_with_attendance_and_delivery():
    record = normalize_professor(FakeProfessor())
    assert record is not None
    assert len(record.ratings) == 1

    rating = record.ratings[0]
    assert rating.rmp_id == 200147
    assert rating.class_code == "CSCE121", "class codes are compacted for joining"
    assert rating.helpful == 5.0
    assert rating.clarity == 4.0
    assert rating.difficulty == 3.0
    assert rating.attendance_mandatory is True
    assert rating.is_online is False
    assert rating.is_for_credit is True
    assert rating.rated_at == datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_course_codes_and_distribution_survive_as_json():
    record = normalize_professor(FakeProfessor())
    assert record is not None
    assert record.course_codes == [{"courseName": "CSCE121", "courseCount": 9}]
    assert record.ratings_distribution["total"] == 12


def test_graphql_edge_shaped_ratings_are_unwrapped():
    professor = FakeProfessor(
        ratings={"edges": [{"node": {"comment": "ok", "class": "MATH151"}}]}
    )
    record = normalize_professor(professor)
    assert record is not None
    assert [r.class_code for r in record.ratings] == ["MATH151"]


def test_dict_payloads_work_as_well_as_objects():
    record = normalize_professor(
        {"legacyId": 42, "firstName": "A", "lastName": "B", "numRatings": 3, "avgRating": 4.2}
    )
    assert record is not None
    assert (record.rmp_id, record.full_name, record.avg_rating) == (42, "A B", 4.2)


def test_blank_comments_become_none():
    rating = normalize_rating({"comment": "   ", "class": "CSCE121"}, rmp_id=1)
    assert rating.comment is None


def test_date_formats():
    assert parse_rmp_date("2012-01-02 00:35:24 +0000 UTC") == datetime(
        2012, 1, 2, 0, 35, 24, tzinfo=timezone.utc
    )
    assert parse_rmp_date("2012-01-02").year == 2012
    assert parse_rmp_date(1_700_000_000).tzinfo is timezone.utc
    assert parse_rmp_date(None) is None
    assert parse_rmp_date("") is None
    assert parse_rmp_date("not a date") is None


def test_to_jsonable_flattens_objects_for_the_raw_column():
    payload = to_jsonable(FakeGist())
    assert payload["legacy_id"] == 200147
    assert payload["school"]["name"] == "Texas A&M University"


def test_raw_payload_is_kept_for_fields_the_scraper_adds_later():
    record = normalize_professor(FakeProfessor())
    assert record is not None
    assert record.raw["lock_status"] == "unlocked"
    assert record.ratings[0].raw["flagStatus"] == "UNFLAGGED"


def test_school_node_id_round_trips():
    """Confirmed against the pipeline's own cache, which stores school 1003
    under exactly this key."""
    from app.services.rmp import school_node_id

    assert school_node_id(1003) == "U2Nob29sLTEwMDM="
    assert decode_node_id(school_node_id(1006)) == 1006


def test_school_id_normalises_whichever_form_the_query_returns():
    """The roster query returns the school's node id, the per-professor query
    returns its legacyId. Rows from both have to be comparable."""
    from_roster = normalize_professor(
        {"legacyId": 1, "firstName": "A", "lastName": "B",
         "school": {"id": "U2Nob29sLTEwMDM=", "name": "Texas A&M University"}}
    )
    from_detail = normalize_professor(
        {"legacyId": 2, "firstName": "C", "lastName": "D",
         "school": {"legacyId": 1003, "id": "U2Nob29sLTEwMDM=", "name": "Texas A&M"}}
    )

    assert from_roster is not None and from_detail is not None
    assert from_roster.school_id == from_detail.school_id == "1003"
