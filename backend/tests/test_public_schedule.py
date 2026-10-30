"""Reading A&M's public class schedule.

Shapes here are copied from real Fall 2026 responses, so a change at the far
end shows up as a failing test rather than as a term that silently loads with
no meeting times.
"""

from __future__ import annotations

import json

import pytest

from app.ingest.load_public_schedule import (
    WEEKLY,
    clock,
    delivery_of,
    instructor_of,
    meetings_of,
    parse_term_desc,
    to_record,
)

# A real row, trimmed to the fields the loader reads.
ROW = {
    "SWV_CLASS_SEARCH_TERM": "202631",
    "SWV_CLASS_SEARCH_CRN": "45405",
    "SWV_CLASS_SEARCH_SUBJECT": "CSCE",
    "SWV_CLASS_SEARCH_COURSE": "110",
    "SWV_CLASS_SEARCH_SECTION": "500",
    "SWV_CLASS_SEARCH_TITLE": "PROGRAMMING I",
    "SWV_CLASS_SEARCH_SITE": "College Station",
    "SWV_CLASS_SEARCH_SCHD": "LL",
    "SWV_CLASS_SEARCH_MAX_ENRL": "120",
    "SWV_CLASS_SEARCH_SEATS_AVAIL": "8",
    "SWV_CLASS_SEARCH_ATTRIBUTES": "",
    "SWV_CLASS_SEARCH_INSTRCTR_JSON": json.dumps(
        [{"NAME": "Ki Hwan K. Yum (P)", "MORE": 749735, "HAS_CV": "Y"}]
    ),
    "SWV_CLASS_SEARCH_JSON_CLOB": json.dumps(
        [
            {
                "SSRMEET_MON_DAY": "M", "SSRMEET_WED_DAY": "W", "SSRMEET_FRI_DAY": "F",
                "SSRMEET_TUE_DAY": None, "SSRMEET_THU_DAY": None,
                "SSRMEET_SAT_DAY": None, "SSRMEET_SUN_DAY": None,
                "SSRMEET_BEGIN_TIME": "01:50 PM", "SSRMEET_END_TIME": "02:40 PM",
                "SSRMEET_BLDG_CODE": "ZACH", "SSRMEET_ROOM_CODE": "310",
                "SSRMEET_MTYP_CODE": "Lecture",
            }
        ]
    ),
}


def row(**kw):
    return {**ROW, **kw}


# --- terms --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("desc", "term", "campus"),
    [
        ("Fall 2026 - College Station", "FALL 2026", "CSTAT"),
        ("Spring 2027 - Galveston", "SPRING 2027", "GALV"),
        ("Fall 2026 - Qatar", "FALL 2026", "QATAR"),
        ("Summer 2027 - College Station", "SUMMER 2027", "CSTAT"),
    ],
)
def test_terms_read_the_way_the_other_loader_writes_them(desc, term, campus):
    assert parse_term_desc(desc) == (term, campus)


@pytest.mark.parametrize("desc", ["Full Yr Professional 2026-2027", "", "Fall - College Station"])
def test_a_term_we_cannot_read_says_so(desc):
    assert parse_term_desc(desc) == (None, None)


# --- clock --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("01:50 PM", "13:50"), ("08:00 AM", "08:00"), ("12:00 PM", "12:00"),
     ("12:30 AM", "00:30"), ("11:59 PM", "23:59"), (None, None), ("", None),
     ("TBA", None), ("25:00 PM", None)],
)
def test_reading_the_clock(raw, expected):
    assert clock(raw) == expected


# --- meetings -----------------------------------------------------------------


def test_one_block_becomes_one_meeting_per_day():
    meetings = meetings_of(ROW["SWV_CLASS_SEARCH_JSON_CLOB"])

    assert [m["day"] for m in meetings] == ["MON", "WED", "FRI"]
    assert all(m["start"] == "13:50" and m["end"] == "14:40" for m in meetings)
    assert meetings[0]["building"] == "ZACH" and meetings[0]["room"] == "310"


def test_an_exam_is_not_a_weekly_meeting():
    """837 of these in Fall 2026. Each would draw a phantom weekly block."""
    exam = json.dumps([{**json.loads(ROW["SWV_CLASS_SEARCH_JSON_CLOB"])[0],
                        "SSRMEET_MTYP_CODE": "Examination"}])

    assert meetings_of(exam) == []


def test_a_lecture_with_no_time_is_not_placed():
    """1,211 of these: a Lecture row with null times and no days."""
    timeless = json.dumps([{"SSRMEET_MTYP_CODE": "Lecture", "SSRMEET_BEGIN_TIME": None,
                            "SSRMEET_END_TIME": None, "SSRMEET_MON_DAY": None}])

    assert meetings_of(timeless) == []


def test_research_and_independent_study_have_no_weekly_slot():
    for kind in ("Research", "Independent Study"):
        block = json.dumps([{**json.loads(ROW["SWV_CLASS_SEARCH_JSON_CLOB"])[0],
                             "SSRMEET_MTYP_CODE": kind}])
        assert meetings_of(block) == [], kind


def test_labs_are_kept_because_students_attend_them():
    lab = json.dumps([{**json.loads(ROW["SWV_CLASS_SEARCH_JSON_CLOB"])[0],
                       "SSRMEET_MTYP_CODE": "Laboratory"}])

    assert len(meetings_of(lab)) == 3
    assert "Laboratory" in WEEKLY


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]"])
def test_unreadable_meetings_are_empty_not_an_error(raw):
    assert meetings_of(raw) == []


# --- instructors --------------------------------------------------------------


def test_the_instructor_of_record_and_their_id():
    assert instructor_of(ROW["SWV_CLASS_SEARCH_INSTRCTR_JSON"]) == ("Ki Hwan K. Yum", 749735)


def test_the_primary_is_chosen_over_a_secondary():
    """Joining the names would invent a person who does not exist."""
    both = json.dumps([
        {"NAME": "Jane A. Doe (S)", "MORE": 1},
        {"NAME": "Ki Hwan K. Yum (P)", "MORE": 749735},
    ])

    assert instructor_of(both) == ("Ki Hwan K. Yum", 749735)


def test_a_section_with_nobody_assigned():
    assert instructor_of("[]") == (None, None)
    assert instructor_of(None) == (None, None)


# --- whole rows ---------------------------------------------------------------


def test_a_real_row_maps_completely():
    record = to_record(row(), "FALL 2026", "CSTAT")

    assert (record.dept, record.number, record.section_code) == ("CSCE", "110", "500")
    assert record.person_id == 749735
    assert record.instructor == "Ki Hwan K. Yum"
    assert record.campus == "CSTAT"
    assert record.delivery == "F2F"
    assert record.seats == 120 and record.seats_open == 8
    assert len(record.meetings) == 3
    assert record.honors is False


def test_honors_is_read_from_the_attributes():
    assert to_record(row(SWV_CLASS_SEARCH_ATTRIBUTES="Honors"), "FALL 2026", "CSTAT").honors


def test_a_section_elsewhere_keeps_its_own_site_not_the_term_s():
    """A College Station term still lists sections taught at Galveston."""
    record = to_record(row(SWV_CLASS_SEARCH_SITE="Galveston"), "FALL 2026", "CSTAT")

    assert record.campus == "GALV"


def test_seats_that_are_not_numbers_are_unknown_rather_than_zero():
    record = to_record(row(SWV_CLASS_SEARCH_SEATS_AVAIL="NA"), "FALL 2026", "CSTAT")

    assert record.seats_open is None, "NA is not a seat count"


def test_a_row_with_no_course_code_is_dropped():
    assert to_record(row(SWV_CLASS_SEARCH_SUBJECT=""), "FALL 2026", "CSTAT") is None
    assert to_record(row(SWV_CLASS_SEARCH_SECTION=""), "FALL 2026", "CSTAT") is None


def test_an_online_site_is_web():
    assert delivery_of({"SWV_CLASS_SEARCH_SITE": "Online"}, []) == "WEB"


def test_delivery_is_unknown_rather_than_guessed():
    """Reading a blank as online would skip the cross-campus travel check."""
    assert delivery_of({}, []) is None
