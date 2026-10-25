"""The ranking math. Mirrors the instructor_scores view in sql/002_indexes.sql."""

from __future__ import annotations

import pytest

from app.scoring import (
    GlobalMeans,
    ScoreWeights,
    composite_from_adjusted,
    gpa_to_rating_scale,
    percent_to_rating_scale,
    rank,
    score_instructor,
    shrink,
)

MEANS = GlobalMeans(rating=3.5, difficulty=3.0, would_take_again=3.0, gpa=3.0)


def test_shrink_returns_the_prior_without_evidence():
    assert shrink(None, 0, 3.5, 10) == 3.5
    assert shrink(5.0, 0, 3.5, 10) == 3.5


def test_shrink_is_halfway_at_the_prior_weight():
    assert shrink(5.0, 10, 3.0, 10) == pytest.approx(4.0)


def test_shrink_approaches_the_observed_value_with_evidence():
    assert shrink(5.0, 1000, 3.0, 10) == pytest.approx(4.98, abs=0.01)


def test_few_glowing_reviews_lose_to_many_good_ones():
    """The requirement from the planning doc, stated as a test."""
    hyped = score_instructor(
        instructor_id=1,
        avg_rating=4.9,
        avg_difficulty=3.0,
        rating_count=2,
        would_take_again_percent=None,
        avg_gpa=None,
        means=MEANS,
    )
    proven = score_instructor(
        instructor_id=2,
        avg_rating=4.6,
        avg_difficulty=3.0,
        rating_count=80,
        would_take_again_percent=None,
        avg_gpa=None,
        means=MEANS,
    )
    assert proven.adj_rating > hyped.adj_rating
    assert rank([hyped, proven])[0].instructor_id == 2


def test_ranking_is_rating_then_difficulty():
    easy = score_instructor(
        instructor_id=1,
        avg_rating=4.0,
        avg_difficulty=2.0,
        rating_count=50,
        would_take_again_percent=None,
        avg_gpa=None,
        means=MEANS,
    )
    hard = score_instructor(
        instructor_id=2,
        avg_rating=4.0,
        avg_difficulty=4.5,
        rating_count=50,
        would_take_again_percent=None,
        avg_gpa=None,
        means=MEANS,
    )
    best = score_instructor(
        instructor_id=3,
        avg_rating=4.8,
        avg_difficulty=4.9,
        rating_count=50,
        would_take_again_percent=None,
        avg_gpa=None,
        means=MEANS,
    )
    # Rating wins outright; difficulty only breaks ties.
    assert [s.instructor_id for s in rank([hard, easy, best])] == [3, 1, 2]


def test_would_take_again_minus_one_is_absent_not_zero():
    assert percent_to_rating_scale(-1) is None
    assert percent_to_rating_scale(100) == 5.0
    assert percent_to_rating_scale(50) == 2.5

    score = score_instructor(
        instructor_id=1,
        avg_rating=4.0,
        avg_difficulty=3.0,
        rating_count=10,
        would_take_again_percent=-1,
        avg_gpa=None,
        means=MEANS,
    )
    assert score.adj_would_take_again is None


def test_gpa_normalises_onto_the_rating_scale_and_clamps():
    assert gpa_to_rating_scale(4.0) == 5.0
    assert gpa_to_rating_scale(2.0) == 2.5
    assert gpa_to_rating_scale(9.9) == 5.0
    assert gpa_to_rating_scale(None) is None


def test_course_mean_is_the_gpa_prior_when_given():
    """A 3.9 in an easy elective should not read like a 3.9 in organic chem."""
    easy_course = score_instructor(
        instructor_id=1,
        avg_rating=4.0,
        avg_difficulty=3.0,
        rating_count=10,
        would_take_again_percent=None,
        avg_gpa=3.9,
        gpa_student_count=30,
        course_mean_gpa=3.8,
        means=MEANS,
    )
    hard_course = score_instructor(
        instructor_id=2,
        avg_rating=4.0,
        avg_difficulty=3.0,
        rating_count=10,
        would_take_again_percent=None,
        avg_gpa=3.9,
        gpa_student_count=30,
        course_mean_gpa=2.4,
        means=MEANS,
    )
    assert hard_course.adj_gpa < easy_course.adj_gpa


def test_composite_applies_weights_and_penalises_difficulty():
    weights = ScoreWeights(rating=1.0, would_take_again=0.0, gpa=0.0, difficulty=-0.5)
    easier = composite_from_adjusted(adj_rating=4.0, adj_difficulty=2.0, weights=weights)
    harder = composite_from_adjusted(adj_rating=4.0, adj_difficulty=4.0, weights=weights)
    assert easier > harder
    assert easier == pytest.approx(3.0)


def test_composite_ignores_missing_components():
    weights = ScoreWeights(rating=1.0, would_take_again=0.3, gpa=0.4, difficulty=-0.5)
    without = composite_from_adjusted(adj_rating=4.0, adj_difficulty=3.0, weights=weights)
    with_both = composite_from_adjusted(
        adj_rating=4.0,
        adj_difficulty=3.0,
        adj_would_take_again=5.0,
        adj_gpa=5.0,
        weights=weights,
    )
    assert with_both > without


def test_weights_come_from_settings(settings):
    weights = ScoreWeights.from_settings(settings)
    assert weights.rating == settings.weight_rating
    assert weights.difficulty == settings.weight_difficulty < 0
