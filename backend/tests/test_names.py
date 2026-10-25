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


# --- the shape A&M's grade reports actually use -------------------------------


def test_a_bare_initial_is_kept_when_it_is_all_that_distinguishes():
    """A&M writes instructors as "RODRIGUEZ C". Dropping that letter would merge
    every professor who shares a surname into one person."""
    assert name_tokens("RODRIGUEZ C") == ["rodriguez", "c"]
    assert canonical_key("RODRIGUEZ C") != canonical_key("RODRIGUEZ J")


def test_a_middle_initial_is_still_dropped_when_the_name_survives_without_it():
    assert name_tokens("DOE, JANE M") == ["jane", "doe"]


def test_initial_form_detection():
    from app.services.names import is_initial_form

    assert is_initial_form("RODRIGUEZ C")
    assert not is_initial_form("Christopher Rodriguez")
    assert not is_initial_form("Madonna")


def test_surname_plus_initial_matches_a_full_name():
    from app.services.names import resolve_name

    roster = {"Christopher Rodriguez": 1, "Jane Rodriguez": 2}
    outcome = resolve_name("RODRIGUEZ C", roster)

    assert outcome.reason == "surname_initial"
    assert outcome.match is not None and outcome.match.value == 1


def test_two_professors_sharing_surname_and_initial_are_ambiguous_not_guessed():
    from app.services.names import resolve_name

    roster = {"Karen Chang": 1, "Kevin Chang": 2}
    outcome = resolve_name("CHANG K", roster)

    assert outcome.reason == "ambiguous"
    assert outcome.match is None
    assert outcome.candidates == ("Karen Chang", "Kevin Chang")


def test_a_mismatched_initial_vetoes_a_surname_only_fuzzy_match():
    """The failure this guards against: "RODRIGUEZ A" scoring high against
    Christopher Rodriguez purely on the shared surname."""
    from app.services.names import resolve_name

    outcome = resolve_name("RODRIGUEZ A", {"Christopher Rodriguez": 1})

    assert outcome.reason == "initial_mismatch"
    assert outcome.match is None


def test_two_full_first_names_are_not_matched_on_their_initial():
    from app.services.names import resolve_name

    outcome = resolve_name("Jonathan Rodriguez", {"Jane Rodriguez": 1})
    assert outcome.match is None


def test_a_bare_surname_with_several_candidates_is_ambiguous():
    from app.services.names import resolve_name

    outcome = resolve_name("RODRIGUEZ", {"Christopher Rodriguez": 1, "Jane Rodriguez": 2})
    assert outcome.reason == "ambiguous"


def test_an_exact_name_still_wins_outright():
    from app.services.names import resolve_name

    outcome = resolve_name("Jane Rodriguez", {"Christopher Rodriguez": 1, "Jane Rodriguez": 2})
    assert outcome.reason == "exact"
    assert outcome.match is not None and outcome.match.value == 2
