"""Ranking math.

The planning doc asks for "a formula to take into account the amount of
ratings/reviews each teacher got". That is Bayesian shrinkage: pull every
average toward the global mean in proportion to how little evidence backs it. A
professor with 4.9 from two reviews lands below one with 4.6 from eighty, which
is the whole point.

These functions mirror the ``instructor_scores`` SQL view in sql/002_indexes.sql.
The view is what the API reads (always current, no recompute job); this module is
what the tests exercise. If you change one, change both -- test_scoring.py checks
the Python side and the shapes are identical by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings

#: RMP ratings and difficulty both live on 1-5.
RATING_SCALE = 5.0
#: A&M GPA is on 0-4; normalising onto 0-5 lets it sit in the same weighted sum.
GPA_SCALE = 4.0


def shrink(value: float | None, count: int | None, prior_mean: float, prior_weight: float) -> float:
    """Blend an observed average toward ``prior_mean``.

    ``prior_weight`` is "how many ratings it takes before I believe you" -- at
    ``count == prior_weight`` the result sits exactly halfway between the
    professor's own average and the global one.
    """
    n = max(0, count or 0)
    if value is None or n == 0:
        return prior_mean
    weight = prior_weight if prior_weight > 0 else 0.0
    return (n * float(value) + weight * prior_mean) / (n + weight)


def gpa_to_rating_scale(gpa: float | None) -> float | None:
    """0-4 GPA onto the 0-5 scale the other components use."""
    if gpa is None:
        return None
    return max(0.0, min(float(gpa), GPA_SCALE)) / GPA_SCALE * RATING_SCALE


def percent_to_rating_scale(percent: float | None) -> float | None:
    """A would-take-again percentage onto 0-5. RMP uses -1 for "no data"."""
    if percent is None or percent < 0:
        return None
    return max(0.0, min(float(percent), 100.0)) / 100.0 * RATING_SCALE


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    rating: float = 1.0
    would_take_again: float = 0.3
    gpa: float = 0.4
    difficulty: float = -0.5

    @classmethod
    def from_settings(cls, settings: Settings) -> "ScoreWeights":
        return cls(
            rating=settings.weight_rating,
            would_take_again=settings.weight_would_take_again,
            gpa=settings.weight_gpa,
            difficulty=settings.weight_difficulty,
        )


@dataclass(frozen=True, slots=True)
class GlobalMeans:
    """Priors, computed once per ingest over every professor in the database."""

    rating: float = 3.5
    difficulty: float = 3.0
    would_take_again: float = 3.0  # already on the 0-5 scale
    gpa: float = 3.0  # on the 0-4 GPA scale


@dataclass(frozen=True, slots=True)
class InstructorScore:
    instructor_id: int
    adj_rating: float
    adj_difficulty: float
    adj_would_take_again: float | None
    adj_gpa: float | None
    composite: float
    rating_count: int

    @property
    def sort_key(self) -> tuple[float, float]:
        """The doc's rule, literally: RMP score first, then difficulty.

        Rating descending (hence the negation), difficulty ascending.
        """
        return (-self.adj_rating, self.adj_difficulty)


def score_instructor(
    *,
    instructor_id: int,
    avg_rating: float | None,
    avg_difficulty: float | None,
    rating_count: int | None,
    would_take_again_percent: float | None,
    avg_gpa: float | None,
    gpa_student_count: int | None = None,
    course_mean_gpa: float | None = None,
    means: GlobalMeans | None = None,
    weights: ScoreWeights | None = None,
    prior_weight: float = 10.0,
) -> InstructorScore:
    """Score one professor (optionally within one course, via ``course_mean_gpa``)."""
    means = means or GlobalMeans()
    weights = weights or ScoreWeights()
    n = max(0, rating_count or 0)

    adj_rating = shrink(avg_rating, n, means.rating, prior_weight)
    adj_difficulty = shrink(avg_difficulty, n, means.difficulty, prior_weight)

    wta = percent_to_rating_scale(would_take_again_percent)
    adj_wta = shrink(wta, n, means.would_take_again, prior_weight) if wta is not None else None

    # Grades shrink toward this course's own mean where we have one, because a
    # 3.9 average in an easy elective is not the same signal as in organic chem.
    gpa_prior = course_mean_gpa if course_mean_gpa is not None else means.gpa
    adj_gpa_raw = (
        shrink(avg_gpa, gpa_student_count or 0, gpa_prior, prior_weight)
        if avg_gpa is not None
        else None
    )
    adj_gpa = gpa_to_rating_scale(adj_gpa_raw)

    composite = weights.rating * adj_rating + weights.difficulty * adj_difficulty
    if adj_wta is not None:
        composite += weights.would_take_again * adj_wta
    if adj_gpa is not None:
        composite += weights.gpa * adj_gpa

    return InstructorScore(
        instructor_id=instructor_id,
        adj_rating=adj_rating,
        adj_difficulty=adj_difficulty,
        adj_would_take_again=adj_wta,
        adj_gpa=adj_gpa,
        composite=composite,
        rating_count=n,
    )


def rank(scores: list[InstructorScore]) -> list[InstructorScore]:
    """Sort by adjusted rating desc, then difficulty asc.

    The composite stays a separate field on purpose: preference-weighted sorting
    ("I want easy tests") can use it later without changing this default.
    """
    return sorted(scores, key=lambda s: s.sort_key)


def composite_from_adjusted(
    *,
    adj_rating: float,
    adj_difficulty: float,
    adj_would_take_again: float | None = None,
    adj_gpa: float | None = None,
    weights: ScoreWeights | None = None,
) -> float:
    """Weight already-shrunk values.

    The ``instructor_scores`` view does the shrinking (it needs database-wide
    aggregates) and stops there; the weighting happens here, from settings. That
    split keeps each half with exactly one source of truth.
    """
    weights = weights or ScoreWeights()
    total = weights.rating * float(adj_rating) + weights.difficulty * float(adj_difficulty)
    if adj_would_take_again is not None:
        total += weights.would_take_again * float(adj_would_take_again)
    if adj_gpa is not None:
        total += weights.gpa * float(adj_gpa)
    return total
