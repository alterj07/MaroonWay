"""The scheduler, and above all the 20-minute minimum gap.

That is the planning doc's single REQUIRED rule, so the awkward cases get
named explicitly: a class ending exactly when the next starts, a gap one
minute short, an online section that cannot clash with anything.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.scheduling import (
    DEFAULT_MIN_GAP_MINUTES,
    Availability,
    Meeting,
    Section,
    clash,
    describe_failure,
    format_time,
    gap_between,
    generate,
    parse_days,
    parse_meetings,
    parse_time,
    summarize,
)


def section(
    code: str,
    section_code: str = "500",
    *,
    days: str = "MWF",
    start: str = "09:10",
    end: str = "10:00",
    rating: float | None = 4.0,
    difficulty: float | None = 3.0,
    gpa: float | None = None,
    campus: str | None = "CSTAT",
    delivery: str | None = "F2F",
    honors: bool = False,
    online: bool = False,
    instructor: str | None = "DOE J",
    reviews: int = 0,
) -> Section:
    meets = (
        ()
        if online
        else parse_meetings([{"days": days, "start": start, "end": end, "building": "ZACH"}])
    )
    return Section(
        section_id=abs(hash((code, section_code))) % 100_000,
        course_id=abs(hash(code)) % 1_000,
        code=code,
        section_code=section_code,
        term="FALL 2026",
        instructor_id=1,
        instructor_name=instructor,
        campus=campus,
        delivery="WEB" if online else delivery,
        honors=honors,
        meetings=meets,
        class_reviews=reviews,
        professor_reviews=reviews,
        adj_rating=rating,
        adj_difficulty=difficulty,
        adj_gpa=gpa,
    )


# --- parsing ------------------------------------------------------------------


def test_compact_day_patterns():
    assert parse_days("MWF") == ("MON", "WED", "FRI")
    assert parse_days("TR") == ("TUE", "THU"), "R is Thursday at A&M"
    assert parse_days("MW") == ("MON", "WED")


def test_day_spellings_and_separators():
    assert parse_days("Mon,Wed") == ("MON", "WED")
    assert parse_days(["TUE", "THURSDAY"]) == ("TUE", "THU")
    assert parse_days("") == ()
    assert parse_days(None) == ()


def test_unparseable_days_are_dropped_not_guessed():
    assert parse_days("by appointment") == ()


def test_time_formats():
    assert parse_time("09:10") == 550
    assert parse_time("0910") == 550
    assert parse_time("1:25 PM") == 805
    assert parse_time("12:00 AM") == 0
    assert parse_time("12:30 PM") == 750
    assert parse_time("nonsense") is None
    assert parse_time(None) is None


def test_format_time_round_trips():
    assert format_time(parse_time("14:05")) == "14:05"


def test_a_meeting_with_no_end_is_skipped():
    assert parse_meetings([{"days": "MWF", "start": "09:10"}]) == ()


def test_a_backwards_meeting_is_skipped():
    assert parse_meetings([{"days": "MON", "start": "10:00", "end": "09:00"}]) == ()


def test_meetings_expand_one_per_day_and_sort_by_week_order():
    meetings = parse_meetings([{"days": "FM", "start": "09:10", "end": "10:00"}])
    assert [m.day for m in meetings] == ["MON", "FRI"]


# --- the gap rule -------------------------------------------------------------


def test_the_default_minimum_is_the_doc_s_twenty_minutes():
    assert DEFAULT_MIN_GAP_MINUTES == 20


def test_overlapping_classes_clash():
    reason = clash(section("CSCE121"), section("MATH151", start="09:30", end="10:20"))
    assert reason is not None and "overlap" in reason


def test_back_to_back_classes_clash_because_of_the_gap_rule():
    """The first ends at 10:00 and the next starts at 10:00: legal on a
    timetable, useless to a student who has to walk."""
    reason = clash(section("CSCE121"), section("MATH151", start="10:00", end="10:50"))
    assert reason is not None and "less than the 20 min required" in reason


def test_a_gap_one_minute_short_still_clashes():
    reason = clash(section("CSCE121"), section("MATH151", start="10:19", end="11:00"))
    assert reason is not None and "19 min" in reason


def test_exactly_twenty_minutes_is_allowed():
    assert clash(section("CSCE121"), section("MATH151", start="10:20", end="11:10")) is None


def test_a_student_can_demand_more_room():
    pair = (section("CSCE121"), section("MATH151", start="10:25", end="11:15"))
    assert clash(*pair, min_gap=20) is None
    assert clash(*pair, min_gap=30) is not None


def test_classes_on_different_days_never_clash():
    assert clash(section("CSCE121", days="MWF"), section("MATH151", days="TR")) is None
    assert gap_between(Meeting("MON", 540, 600), Meeting("TUE", 540, 600)) is None


def test_an_online_section_cannot_clash_with_anything():
    online = section("ENGL104", online=True)
    assert online.is_online
    assert clash(online, section("CSCE121")) is None
    assert clash(online, section("MATH151", start="09:10", end="10:00")) is None


@pytest.mark.parametrize("delivery", ["F2F", "HYBRID", None])
def test_missing_times_are_not_evidence_that_a_section_is_online(delivery):
    unknown = replace(section("CSCE121", delivery=delivery), meetings=())
    assert not unknown.is_online
    assert generate({"CSCE121": [unknown]}) == []
    reason = describe_failure({"CSCE121": [unknown]})
    assert "CSCE121" in reason and "meeting times" in reason


def test_an_unknown_time_section_cannot_pair_with_a_different_campus():
    unknown = replace(section("CSCE121", campus="GALV"), meetings=())
    known = section("MATH151", campus="CSTAT")
    assert clash(unknown, known) is not None
    assert generate({"CSCE121": [unknown], "MATH151": [known]}) == []


def test_a_known_time_alternative_is_used_instead_of_an_unknown_time_section():
    unknown = replace(section("CSCE121", "500", rating=5.0), meetings=())
    known = section("CSCE121", "501", rating=3.0)
    results = generate({"CSCE121": [unknown, known]})
    assert len(results) == 1
    assert results[0].sections == (known,)


def test_synchronous_online_meetings_still_obey_time_conflicts():
    online = section("CSCE121", delivery="WEB", campus="GALV")
    assert online.is_online
    assert clash(online, section("MATH151", campus="CSTAT")) is not None
    later = section("MATH151", start="10:30", end="11:20", campus="CSTAT")
    assert clash(online, later) is None


# --- generating ---------------------------------------------------------------


def test_a_single_course_yields_one_schedule_per_section():
    schedules = generate({"CSCE121": [section("CSCE121", "500"), section("CSCE121", "501")]})
    assert len(schedules) == 2


def test_only_conflict_free_combinations_come_back():
    schedules = generate(
        {
            "CSCE121": [section("CSCE121", "500", start="09:10", end="10:00")],
            # 501 is back-to-back (illegal), 502 leaves 25 minutes (legal).
            "MATH151": [
                section("MATH151", "501", start="10:00", end="10:50"),
                section("MATH151", "502", start="10:25", end="11:15"),
            ],
        }
    )
    assert len(schedules) == 1
    assert [s.section_code for s in schedules[0].sections] == ["500", "502"]
    assert schedules[0].tightest_gap == 25


def test_schedules_are_ranked_by_rating_then_difficulty():
    """The doc's rule, as a test."""
    schedules = generate(
        {
            "CSCE121": [
                section("CSCE121", "A", rating=4.8, difficulty=4.9, days="MWF"),
                section("CSCE121", "B", rating=4.0, difficulty=2.0, days="MWF"),
                section("CSCE121", "C", rating=4.0, difficulty=4.0, days="MWF"),
            ]
        }
    )
    assert [s.sections[0].section_code for s in schedules] == ["A", "B", "C"]


def test_an_impossible_request_returns_nothing_rather_than_a_partial_schedule():
    assert (
        generate(
            {
                "CSCE121": [section("CSCE121", "500", start="09:10", end="10:00")],
                "MATH151": [section("MATH151", "501", start="09:30", end="10:20")],
            }
        )
        == []
    )


def test_availability_windows_exclude_sections():
    early = section("CSCE121", "500", start="08:00", end="08:50")
    later = section("CSCE121", "501", start="13:00", end="13:50")
    schedules = generate(
        {"CSCE121": [early, later]}, availability=Availability(earliest=parse_time("09:00"))
    )
    assert [s.sections[0].section_code for s in schedules] == ["501"]


def test_a_student_can_refuse_a_whole_day():
    schedules = generate(
        {"CSCE121": [section("CSCE121", "500", days="MWF"), section("CSCE121", "501", days="TR")]},
        availability=Availability(excluded_days=frozenset({"FRI"})),
    )
    assert [s.sections[0].section_code for s in schedules] == ["501"]


def test_an_online_section_survives_any_availability():
    schedules = generate(
        {"ENGL104": [section("ENGL104", "W01", online=True)]},
        availability=Availability(earliest=parse_time("23:00"), excluded_days=frozenset(DAYS_ALL)),
    )
    assert len(schedules) == 1


DAYS_ALL = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def test_the_limit_is_respected():
    pool = [section("CSCE121", f"5{i:02d}", days="MWF", start=f"{8 + i}:00", end=f"{8 + i}:50")
            for i in range(6)]
    assert len(generate({"CSCE121": pool}, limit=3)) == 3


# --- explaining failure -------------------------------------------------------


def test_a_course_with_no_sections_is_named():
    assert "no sections on record for MATH151" in describe_failure(
        {"CSCE121": [section("CSCE121")], "MATH151": []}
    )


def test_availability_that_excludes_everything_is_named():
    message = describe_failure(
        {"CSCE121": [section("CSCE121", start="08:00", end="08:50")]},
        availability=Availability(earliest=parse_time("12:00")),
    )
    assert "outside your availability" in message


def test_an_unavoidable_clash_is_explained():
    message = describe_failure(
        {
            "CSCE121": [section("CSCE121", "500", start="09:10", end="10:00")],
            "MATH151": [section("MATH151", "501", start="09:30", end="10:20")],
        }
    )
    assert "overlaps" in message or "cannot be combined" in message


# --- summarising --------------------------------------------------------------


def test_summary_reports_the_tightest_gap_and_the_week_shape():
    schedule = summarize(
        [
            section("CSCE121", days="MWF", start="09:10", end="10:00"),
            section("MATH151", days="MWF", start="10:30", end="11:20"),
            section("ENGL104", days="TR", start="14:00", end="15:15"),
        ]
    )
    assert schedule.tightest_gap == 30
    assert schedule.days_on_campus == 5
    assert schedule.earliest_start == parse_time("09:10")


def test_summary_falls_back_when_no_section_has_a_rating():
    schedule = summarize([section("CSCE121", rating=None, difficulty=None)])
    assert schedule.mean_rating == pytest.approx(3.5)
    assert schedule.mean_gpa is None


def test_the_failure_message_names_the_near_miss():
    """Of several blocked pairings, the useful one to report is the closest to
    working, because that is the number the student can relax."""
    message = describe_failure(
        {
            "CSCE121": [
                section("CSCE121", "500", start="09:10", end="10:00"),
                section("CSCE121", "501", start="10:00", end="10:50"),
            ],
            "MATH151": [section("MATH151", "200", start="10:20", end="11:10")],
        },
        min_gap=90,
    )
    assert "closest any two of their sections come is 20 min" in message
    assert "less than the 90 min required" in message


class TestCampusConflicts:
    """A&M teaches the same numbers at three campuses."""

    def _section(
        self, code: str, campus: str | None, day: str, start: str, end: str
    ) -> Section:
        return Section(
            section_id=abs(hash((code, campus, day, start))) % 100_000,
            course_id=abs(hash(code)) % 1000,
            code=code,
            section_code="501",
            term="FALL 2026",
            campus=campus,
            meetings=(Meeting(day=day, start=start, end=end),),
        )

    def test_different_campuses_cannot_both_be_attended(self) -> None:
        here = self._section("ACCT229", "CSTAT", "MON", "09:00", "09:50")
        away = self._section("ENGL104", "GALV", "WED", "13:00", "13:50")
        reason = clash(here, away)
        assert reason is not None
        assert "CSTAT" in reason and "GALV" in reason

    def test_same_campus_is_fine_when_the_times_work(self) -> None:
        a = self._section("ACCT229", "CSTAT", "MON", "09:00", "09:50")
        b = self._section("ENGL104", "CSTAT", "WED", "13:00", "13:50")
        assert clash(a, b) is None

    def test_an_online_section_pairs_with_any_campus(self) -> None:
        """No meetings means no campus to travel to."""
        online = Section(
            section_id=1,
            course_id=9,
            code="ENGL104",
            section_code="M99",
            term="FALL 2026",
            campus="GALV",
            delivery="WEB",
            meetings=(),
        )
        assert clash(self._section("ACCT229", "CSTAT", "MON", "09:00", "09:50"), online) is None

    def test_an_unknown_campus_is_not_treated_as_a_conflict(self) -> None:
        """Most rows have a campus now, but not all; absence is not evidence."""
        known = self._section("ACCT229", "CSTAT", "MON", "09:00", "09:50")
        unknown = self._section("ENGL104", None, "WED", "13:00", "13:50")
        assert clash(known, unknown) is None


class TestStatedConstraintsAreApplied:
    """A clear preference has to shape the search, not just score it.

    With a hundred sections to a course the candidate pool fills with the
    highest-rated combinations long before a Friday-free or late-starting one
    appears, so a preference that only scores is a preference that does
    nothing.
    """

    def _section(self, code: str, day: str, start: str, end: str, rating: float) -> Section:
        # Meeting times are minutes since midnight, the way parse_meetings
        # stores them; parse_time is what does that conversion in production.
        return Section(
            section_id=abs(hash((code, day, start))) % 100_000,
            course_id=abs(hash(code)) % 1000,
            code=code,
            section_code="500",
            term="SPRING 2027",
            adj_rating=rating,
            meetings=(
                Meeting(
                    day=day,
                    start=parse_time(start) or 0,
                    end=parse_time(end) or 0,
                ),
            ),
        )

    def test_an_earliest_time_excludes_the_eight_am(self) -> None:
        early = self._section("CSCE222", "TUE", "08:00", "09:15", 4.9)
        later = self._section("CSCE222", "TUE", "10:20", "11:35", 3.1)
        # Highest rated first, so without the constraint the 8am wins.
        unconstrained = generate({"CSCE222": [early, later]}, limit=1)
        assert unconstrained[0].sections[0].meetings[0].start == 8 * 60

        constrained = generate(
            {"CSCE222": [early, later]},
            availability=Availability(earliest=9 * 60),
            limit=1,
        )
        assert constrained
        assert constrained[0].sections[0].meetings[0].start == 10 * 60 + 20

    def test_excluding_friday_excludes_the_friday_section(self) -> None:
        friday = self._section("ENGL203", "FRI", "10:20", "11:35", 4.9)
        tuesday = self._section("ENGL203", "TUE", "10:20", "11:35", 3.1)
        kept = generate(
            {"ENGL203": [friday, tuesday]},
            availability=Availability(excluded_days=frozenset({"FRI"})),
            limit=1,
        )
        assert kept
        assert kept[0].sections[0].meetings[0].day == "TUE"

    def test_an_impossible_constraint_yields_nothing_to_fall_back_from(self) -> None:
        """The caller needs an empty result to know it must relax and say so."""
        only_early = self._section("CSCE222", "TUE", "08:00", "09:15", 4.9)
        assert (
            generate(
                {"CSCE222": [only_early]},
                availability=Availability(earliest=9 * 60),
                limit=1,
            )
            == []
        )
