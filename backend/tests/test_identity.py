"""Deciding which RMP profile is which instructor.

The case that matters is the namesake. "KIM J" is ten different people at
College Station, and the product promise is that each of them gets the right
rating rather than none of them getting any.
"""

from __future__ import annotations

import pytest

from app.services.identity import (
    MARGIN,
    Candidate,
    Name,
    Person,
    names_agree,
    read_name,
    resolve,
    subject_affinity,
    subject_of,
    subject_weights,
)


# --- reading names ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "surname", "given"),
    [
        ("YUM K", "YUM", "K"),                      # grade reports
        ("Yum, Ki Hwan K", "YUM", "KI"),            # registry exports
        ("Ki Hwan K. Yum (P)", "YUM", "KI"),        # public class search
        ("Ki Hwan K. Yum (S)", "YUM", "KI"),        # a secondary instructor
        ("VAN DER BERG J", "VAN DER BERG", "J"),    # surnames with spaces
        ("Chupp, Jesse A Jr", "CHUPP", "JESSE"),    # suffixes are not names
        ("Núñez, José", "NUNEZ", "JOSE"),           # accents fold, not drop
    ],
)
def test_the_name_forms_we_actually_receive(raw, surname, given):
    assert read_name(raw) == Name(surname, given)


@pytest.mark.parametrize("raw", ["STAFF", "TBA", "", None, "   ", "(P)"])
def test_what_is_not_a_name(raw):
    assert read_name(raw) is None


def test_a_role_mark_is_not_part_of_a_surname():
    """"(P)" marks the instructor of record and would otherwise become a name."""
    assert read_name("Lee (P)") is None, "one word and a role mark is still one word"


# --- agreeing on a name -------------------------------------------------------


def test_an_initial_agrees_with_the_name_it_abbreviates():
    assert names_agree(Name("YUM", "K"), Name("YUM", "KI"))
    assert names_agree(Name("YUM", "KI"), Name("YUM", "K"))


def test_different_surnames_never_agree():
    assert not names_agree(Name("YUM", "KI"), Name("YUMA", "KI"))


def test_different_given_names_do_not_agree():
    assert not names_agree(Name("KIM", "JUNE"), Name("KIM", "JAMES"))


def test_a_longer_name_is_not_automatically_a_different_one():
    assert names_agree(Name("KIM", "JUSTIN"), Name("KIM", "JUSTINE"))


# --- subject affinity ---------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "subject"),
    [("CSCE121", "CSCE"), ("CSCE 121", "CSCE"), ("csce121", "CSCE"),
     ("MATH151H", "MATH"), ("", ""), (None, ""), ("121", "")],
)
def test_reading_the_subject_off_a_course_code(code, subject):
    assert subject_of(code) == subject


def test_weights_are_shares_of_someone_s_teaching():
    weights = subject_weights({"ENGL104": 3, "ENGL203": 1})

    assert weights == {"ENGL": 1.0}


def test_a_professor_of_one_subject_matches_a_profile_in_that_subject():
    assert subject_affinity({"ENGL104": 5}, {"ENGL203": 9}) == pytest.approx(1.0)


def test_english_and_gender_studies_are_not_the_same_person():
    """The user's case: five English sections is not the gender studies lecturer."""
    assert subject_affinity({"ENGL104": 5}, {"WGST200": 6}) == pytest.approx(0.0)


def test_a_mostly_csce_professor_still_matches_a_mostly_csce_profile():
    """One cross-listed section must not read as a different person."""
    mine = {"CSCE121": 4, "ENGR102": 1}
    theirs = {"CSCE121": 8, "ENGR102": 2}

    assert subject_affinity(mine, theirs) == pytest.approx(1.0)


def test_the_balance_of_subjects_matters_not_merely_their_presence():
    """A set overlap would score these identically; the product turns on not."""
    mine = {"CSCE121": 9, "ENGR102": 1}
    same_balance = subject_affinity(mine, {"CSCE121": 18, "ENGR102": 2})
    inverted = subject_affinity(mine, {"CSCE121": 2, "ENGR102": 18})

    assert same_balance > inverted
    assert inverted == pytest.approx(0.2)


def test_no_courses_on_record_is_no_evidence_rather_than_disagreement():
    assert subject_affinity({}, {"CSCE121": 4}) == 0.0
    assert subject_affinity({"CSCE121": 4}, {}) == 0.0


# --- resolving ----------------------------------------------------------------


def person(**kw) -> Person:
    base = dict(person_id=749735, full_name="Ki Hwan K. Yum (P)",
                courses={"CSCE110": 2, "CSCE121": 3}, campus="CSTAT")
    return Person(**{**base, **kw})


def candidate(rmp_id: int, **kw) -> Candidate:
    base = dict(full_name="Ki Hwan Yum", department="Computer Science",
                courses={"CSCE121": 10}, campus="CSTAT", rating_count=20)
    return Candidate(rmp_id=rmp_id, **{**base, **kw})


def test_one_profile_with_the_name_is_that_profile():
    """97% of cases. Asking affinity to confirm would throw them away."""
    result = resolve(person(), [candidate(1)])

    assert result.rmp_id == 1
    assert result.basis == "unique"
    assert result.confidence == 1.0


def test_a_unique_name_matches_even_with_no_courses_on_either_side():
    result = resolve(person(courses={}), [candidate(1, courses={})])

    assert result.rmp_id == 1, "no course data is not a reason to withhold a rating"


def test_namesakes_are_separated_by_what_they_teach():
    """The KIM J case: ten people, one name, ten different subjects."""
    engineer = candidate(1, courses={"CSCE121": 12}, department="Computer Science")
    historian = candidate(2, courses={"HIST105": 14}, department="History")

    result = resolve(person(), [historian, engineer])

    assert result.rmp_id == 1
    assert result.basis == "affinity"
    assert "CSCE" in result.reason


def test_namesakes_teaching_the_same_thing_are_not_guessed_at():
    result = resolve(person(), [candidate(1), candidate(2)])

    assert result.rmp_id is None
    assert result.basis == "ambiguous"
    assert result.runner_up is not None


def test_namesakes_with_no_courses_on_record_are_not_guessed_at():
    result = resolve(person(), [candidate(1, courses={}), candidate(2, courses={})])

    assert result.rmp_id is None
    assert result.basis == "ambiguous"
    assert "nothing on record" in result.reason


def test_a_win_inside_the_margin_is_not_a_win():
    """Two profiles a hair apart are a coin toss, and a coin toss is wrong."""
    close = candidate(2, courses={"CSCE121": 9, "HIST105": 1})

    result = resolve(person(courses={"CSCE121": 10}), [candidate(1), close])

    assert result.rmp_id is None
    assert result.basis == "ambiguous"
    assert result.confidence - subject_affinity({"CSCE121": 10}, close.courses) < MARGIN


def test_nobody_by_that_name_says_so():
    result = resolve(person(), [candidate(1, full_name="Jesse Chupp")])

    assert result.rmp_id is None
    assert result.basis == "no_candidates"


def test_an_unreadable_instructor_name_is_reported_not_crashed_on():
    result = resolve(person(full_name="STAFF"), [candidate(1)])

    assert result.rmp_id is None
    assert result.basis == "unreadable_name"


def test_a_different_campus_is_a_different_person():
    result = resolve(person(), [candidate(1, campus="GALV")])

    assert result.rmp_id is None
    assert result.basis == "no_candidates"


def test_an_unknown_campus_on_either_side_does_not_exclude():
    """Missing metadata must not hide a real professor."""
    assert resolve(person(campus=None), [candidate(1)]).rmp_id == 1
    assert resolve(person(), [candidate(1, campus=None)]).rmp_id == 1


def test_every_resolution_carries_the_person_id_it_was_asked_about():
    """Identity is keyed on A&M's id, so it has to survive the round trip."""
    for result in (
        resolve(person(), [candidate(1)]),
        resolve(person(), []),
        resolve(person(full_name="STAFF"), []),
    ):
        assert result.person_id == 749735
