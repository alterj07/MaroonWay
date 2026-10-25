from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.schemas import PreferenceRequest, ScheduleRequest
from app.services import scheduling
from tests.test_scheduling import section


@pytest.mark.parametrize("field, value", [
    ("earliest", "garbage"), ("earliest", "25:00"), ("latest", "24:59"),
    ("excluded_days", ["FUNDAY"]), ("courses", [" "]), ("term", " "),
])
def test_invalid_schedule_constraints_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ScheduleRequest(**{"term": "FALL 2026", "courses": ["CSCE121"], field: value})


def test_common_course_spellings_and_repeated_courses_are_normalized():
    request = ScheduleRequest(term="FALL 2026", courses=[" csce 121 ", "CSCE121", "math-151"])
    assert request.courses == ["CSCE121", "MATH151"]


def test_a_reversed_availability_window_is_rejected():
    with pytest.raises(ValidationError):
        ScheduleRequest(term="FALL 2026", courses=["CSCE121"], earliest="17:00", latest="09:00")


def test_blank_preference_text_does_not_trigger_an_ai_request():
    assert ScheduleRequest(term="FALL 2026", courses=["CSCE121"], wants="   ").wants is None
    with pytest.raises(ValidationError):
        PreferenceRequest(wants="   ")


@pytest.mark.parametrize("clock", ["24:59", "13:00 PM", "00:30 AM"])
def test_impossible_clock_times_are_not_accepted(clock):
    assert scheduling.parse_time(clock) is None


def test_failed_searches_are_bounded_and_not_reported_as_proven_impossible():
    candidates = {
        "A": [section("A", str(i), days="M") for i in range(10)],
        "B": [section("B", str(i), days="T") for i in range(10)],
        "C": [section("C", str(i), days="W") for i in range(10)],
        "D": [section("D", str(i), days="R") for i in range(10)],
        "E": [section("E", str(i), days="M") for i in range(10)],
    }
    with patch.object(scheduling, "clash", wraps=scheduling.clash) as checks:
        try:
            scheduling.generate(candidates, max_combinations=20)
        except RuntimeError as exc:
            assert "search limit" in str(exc).lower()
        else:
            pytest.fail("Search exhaustion must not claim no timetable exists")
    assert checks.call_count <= 80
