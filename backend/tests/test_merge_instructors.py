"""Folding an instructor's history onto the row that teaches their classes.

The table holds the same person under three spellings -- "CANTU J" from the
grade reports, "Justin Cantu" from RateMyProfessors, "Justin Colt Cantu" from
the class schedule -- and the scheduler reads only the last of them. These
tests are about which of those folds are safe, because the unsafe ones put one
professor's rating under another professor's name.
"""

from __future__ import annotations

from app.ingest.merge_instructors import Row, plan_merges


def teaching(id: int, name: str, **kw) -> Row:
    """A row A&M's class schedule identified: what sections point at."""
    return Row(id=id, full_name=name, person_id=700_000 + id, **kw)


def loose(id: int, name: str, **kw) -> Row:
    """A row from the grade reports or RateMyProfessors, with no A&M id."""
    return Row(id=id, full_name=name, **kw)


# --- the repair this exists for -----------------------------------------------


def test_an_abbreviated_name_folds_into_the_full_one():
    plan = plan_merges([teaching(1, "Justin Colt Cantu"), loose(2, "CANTU J", rmp_id=55)])

    assert [(m.keep, m.drop) for m in plan.merges] == [(1, 2)]


def test_the_row_the_scheduler_reads_is_the_one_kept():
    """Sections point at the identified row. Keeping the other would orphan them."""
    plan = plan_merges([loose(2, "CANTU J", rmp_id=55), teaching(1, "Justin Colt Cantu")])

    assert plan.merges[0].keep == 1, "the row carrying the A&M person id survives"
    assert plan.merges[0].drop == 2


def test_a_rating_reaching_a_teaching_row_is_the_point():
    rows = [teaching(1, "Hyunyoung Lee"), loose(2, "LEE H", rmp_id=99)]

    plan = plan_merges(rows)

    assert plan.merges and plan.merges[0].drop == 2


# --- refusing to guess --------------------------------------------------------


def test_a_name_ten_people_answer_to_is_merged_into_none_of_them():
    """"KIM J" fits every Kim in the schedule; one of them would get it wrong."""
    rows = [
        teaching(1, "Jaehyun Kim"),
        teaching(2, "Joon Kim"),
        teaching(3, "Julia Kim"),
        loose(9, "KIM J", rmp_id=42),
    ]

    plan = plan_merges(rows)

    assert plan.merges == []
    assert plan.contested == 3


def test_an_instructor_fitting_two_loose_rows_is_left_alone():
    rows = [teaching(1, "Jane Doe"), loose(2, "DOE J", rmp_id=1), loose(3, "Jane Doe", rmp_id=2)]

    plan = plan_merges(rows)

    assert plan.merges == []
    assert plan.contested == 1


def test_a_single_fit_that_someone_else_also_fits_is_not_a_single_fit():
    """Unique one way round is not unique. Both directions have to be checked."""
    rows = [teaching(1, "Joon Kim"), teaching(2, "Julia Kim"), loose(9, "KIM J")]

    plan = plan_merges(rows)

    assert plan.merges == []
    assert plan.contested == 2


def test_two_profiles_disagreeing_on_who_this_is_are_not_merged():
    rows = [teaching(1, "Justin Colt Cantu", rmp_id=55), loose(2, "CANTU J", rmp_id=77)]

    plan = plan_merges(rows)

    assert plan.merges == []
    assert plan.conflicting == 1
    keep, drop = plan.conflicts[0]
    assert (keep.rmp_id, drop.rmp_id) == (55, 77), "both links are named so one can be fixed"


def test_the_same_profile_on_both_rows_still_merges():
    """Not a disagreement -- the pipeline linked both spellings to one person."""
    rows = [teaching(1, "Justin Colt Cantu", rmp_id=55), loose(2, "CANTU J", rmp_id=55)]

    plan = plan_merges(rows)

    assert len(plan.merges) == 1


def test_different_surnames_are_different_people():
    plan = plan_merges([teaching(1, "Jane Doe"), loose(2, "DOUGH J", rmp_id=1)])

    assert plan.merges == []
    assert plan.alone == 1


def test_different_given_names_are_different_people():
    plan = plan_merges([teaching(1, "James Kim"), loose(2, "KIM JUNE", rmp_id=1)])

    assert plan.merges == []
    assert plan.alone == 1


# --- counting -----------------------------------------------------------------


def test_an_instructor_with_no_history_is_counted_not_merged():
    plan = plan_merges([teaching(1, "Ada Lovelace")])

    assert plan.merges == []
    assert plan.alone == 1


def test_an_unreadable_name_is_reported_rather_than_merged():
    plan = plan_merges([teaching(1, "STAFF"), loose(2, "STAFF", rmp_id=1)])

    assert plan.merges == []
    assert plan.unreadable == 1


def test_loose_rows_are_never_merged_into_each_other():
    """Neither is what the scheduler reads, so folding them fixes nothing."""
    plan = plan_merges([loose(1, "CANTU J", rmp_id=1), loose(2, "Justin Colt Cantu")])

    assert plan.merges == []


def test_a_surname_with_a_particle_still_finds_its_abbreviation():
    rows = [teaching(1, "Jan van der Berg"), loose(2, "VAN DER BERG J", rmp_id=3)]

    assert len(plan_merges(rows).merges) == 1


def test_every_merge_names_both_rows_so_a_wrong_one_can_be_found_later():
    plan = plan_merges([teaching(1, "Justin Colt Cantu"), loose(2, "CANTU J")])

    assert "CANTU J" in plan.merges[0].reason
    assert "Justin Colt Cantu" in plan.merges[0].reason


def test_no_row_is_merged_away_twice():
    """Two keeps claiming one drop would delete a row still referenced."""
    rows = [
        teaching(1, "Justin Cantu"),
        teaching(2, "Justin Colt Cantu"),
        loose(3, "CANTU J", rmp_id=5),
    ]

    plan = plan_merges(rows)

    drops = [m.drop for m in plan.merges]
    assert len(drops) == len(set(drops))
    assert plan.merges == [], "both Justins fit, so neither may take the row"
