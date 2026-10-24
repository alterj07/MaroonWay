"""Name matching between the grades CSV and RateMyProfessors."""

from __future__ import annotations

from app.services.names import (
    DEFAULT_FLOOR,
    canonical_key,
    match_name,
    name_tokens,
    normalize_name,
    similarity,
)


def test_surname_first_with_a_comma_is_reordered():
    assert normalize_name("DOE, JOHN M") == "john doe"


def test_titles_suffixes_and_initials_are_dropped():
    assert normalize_name("Dr. John A. Doe Jr.") == "john doe"
    assert name_tokens("DOE, JOHN M.") == ["john", "doe"]


def test_accents_and_hyphens_fold():
    assert normalize_name("Renée Smith-Jones") == "renee smith jones"


def test_canonical_key_is_order_insensitive():
    """The CSV writes surnames first with no comma to reveal it."""
    assert canonical_key("DOE JOHN") == canonical_key("John Doe")
    assert canonical_key("DOE, JOHN") == canonical_key("john doe")


def test_empty_input_is_empty_not_an_error():
    assert normalize_name(None) == ""
    assert normalize_name("  ") == ""
    assert similarity("", "John Doe") == 0.0


def test_exact_match_wins_and_is_labelled():
    hit = match_name("DOE, JOHN M", {"John Doe": 7, "Jane Doe": 8})
    assert hit is not None
    assert (hit.value, hit.score, hit.method) == (7, 100.0, "exact")
    assert hit.is_exact


def test_fuzzy_match_above_the_floor():
    hit = match_name("Jonathan Doe", {"Jonathon Doe": 11})
    assert hit is not None
    assert hit.value == 11
    assert hit.score >= DEFAULT_FLOOR
    assert hit.method.startswith("fuzzy:")


def test_a_different_person_is_no_match_rather_than_a_guess():
    assert match_name("Alice Zhang", {"John Doe": 1, "Jane Roe": 2}) is None


def test_no_candidates_is_no_match():
    assert match_name("John Doe", {}) is None
    assert match_name("", {"John Doe": 1}) is None


def test_middle_initial_only_differences_still_match():
    hit = match_name("John Q Doe", {"John Doe": 5})
    assert hit is not None and hit.is_exact
