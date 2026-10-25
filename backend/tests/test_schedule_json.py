"""Reading A&M's Compass class-search cache -- the first real meeting times."""

from __future__ import annotations

import json

import pytest

from app.ingest.load_schedule_json import (
    campus_of,
    delivery_of,
    is_honors,
    meetings_of,
    parse_clock,
    parse_records,
    primary_instructor,
    term_name,
)


class TestTermCodes:
    """YYYYSC: season digit then campus digit."""

    @pytest.mark.parametrize(
        ("code", "term", "campus"),
        [
            ("202711", "SPRING 2027", "CSTAT"),
            ("202712", "SPRING 2027", "GALV"),
            ("202731", "FALL 2027", "CSTAT"),
            ("202721", "SUMMER 2027", "CSTAT"),
        ],
    )
    def test_code_splits_into_term_and_campus(self, code, term, campus) -> None:
        assert term_name(code) == term
        assert campus_of(code) == campus

    def test_an_unreadable_code_is_no_term(self) -> None:
        assert term_name("nonsense") is None


class TestClock:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("10:05 AM", "10:05"),
            ("01:20 PM", "13:20"),
            ("12:00 PM", "12:00"),  # noon is 12, not 24
            ("12:30 AM", "00:30"),  # midnight is 00, not 12
            ("8:00 AM", "08:00"),
            ("", None),
            (None, None),
            ("TBA", None),
        ],
    )
    def test_twelve_hour_clock(self, value, expected) -> None:
        assert parse_clock(value) == expected


class TestMeetings:
    def _clob(self, **over) -> str:
        row = {
            "SSRMEET_SUN_DAY": None,
            "SSRMEET_MON_DAY": "M",
            "SSRMEET_TUE_DAY": None,
            "SSRMEET_WED_DAY": "W",
            "SSRMEET_THU_DAY": None,
            "SSRMEET_FRI_DAY": "F",
            "SSRMEET_SAT_DAY": None,
            "SSRMEET_BEGIN_TIME": "09:10 AM",
            "SSRMEET_END_TIME": "10:00 AM",
            "SSRMEET_BLDG_CODE": "ZACH",
            "SSRMEET_ROOM_CODE": "350",
        }
        row.update(over)
        return json.dumps([row])

    def test_one_entry_per_day_the_pattern_meets(self) -> None:
        meetings = meetings_of(self._clob())
        assert [m["day"] for m in meetings] == ["MON", "WED", "FRI"]
        assert all(m["start"] == "09:10" and m["end"] == "10:00" for m in meetings)
        assert meetings[0]["building"] == "ZACH"
        assert meetings[0]["room"] == "350"

    def test_thursday_is_r(self) -> None:
        clob = self._clob(
            SSRMEET_MON_DAY=None,
            SSRMEET_WED_DAY=None,
            SSRMEET_FRI_DAY=None,
            SSRMEET_TUE_DAY="T",
            SSRMEET_THU_DAY="R",
        )
        assert [m["day"] for m in meetings_of(clob)] == ["TUE", "THU"]

    def test_a_section_with_no_clock_has_no_meetings(self) -> None:
        """Online and arranged sections are legitimate, not errors."""
        assert meetings_of(self._clob(SSRMEET_BEGIN_TIME=None, SSRMEET_END_TIME=None)) == []

    @pytest.mark.parametrize("value", ["", None, "not json", "{}", "[]"])
    def test_an_unreadable_clob_is_no_meetings(self, value) -> None:
        assert meetings_of(value) == []


class TestInstructors:
    def test_the_primary_is_preferred_and_the_marker_stripped(self) -> None:
        raw = json.dumps(
            [{"NAME": "Bob Jones (S)"}, {"NAME": "Jacqueline D. Knoop (P)"}]
        )
        assert primary_instructor(raw) == "Jacqueline D. Knoop"

    def test_falls_back_to_the_first_when_none_is_marked(self) -> None:
        assert primary_instructor(json.dumps([{"NAME": "Ann Lee"}])) == "Ann Lee"

    @pytest.mark.parametrize("value", ["", None, "[]", "not json"])
    def test_no_staff_listed(self, value) -> None:
        assert primary_instructor(value) is None


class TestSectionFlags:
    def test_delivery_from_the_instruction_type(self) -> None:
        assert delivery_of({"SWV_CLASS_SEARCH_INST_TYPE": "Web Based"}) == "WEB"
        assert delivery_of({"SWV_CLASS_SEARCH_INST_TYPE": "Face to Face"}) == "F2F"
        assert delivery_of({}) is None

    def test_honors_from_the_title_or_the_attributes(self) -> None:
        assert is_honors({"SWV_CLASS_SEARCH_TITLE": "HNR-INTRO ACCOUNTING"})
        assert is_honors({"SWV_CLASS_SEARCH_ATTRIBUTES": "Honors Program"})
        assert not is_honors({"SWV_CLASS_SEARCH_TITLE": "INTRO ACCOUNTING"})


class TestParseRecords:
    def test_titles_track_the_rows_that_survived(self) -> None:
        """A dropped record must not shift the titles onto another course."""
        good = {
            "SWV_CLASS_SEARCH_TERM": "202711",
            "SWV_CLASS_SEARCH_SUBJECT": "CSCE",
            "SWV_CLASS_SEARCH_COURSE": "691",
            "SWV_CLASS_SEARCH_SECTION": "500",
            "SWV_CLASS_SEARCH_TITLE": "RESEARCH",
        }
        bad = {"SWV_CLASS_SEARCH_TERM": "nonsense"}
        rows, skipped, titles = parse_records([bad, good, bad])
        assert len(rows) == 1
        assert rows[0].dept == "CSCE" and rows[0].number == "691"
        assert titles == {("CSCE", "691"): "RESEARCH"}
        assert skipped["unparsed_term"] == 2
