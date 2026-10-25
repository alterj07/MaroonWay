"""Turning what a student wants into a ranking.

Two halves, both driven by Jev:

1. **Intake.** The student says what they want in their own words. Jev answers a
   fixed set of typed questions about that text, which become weights. The
   dimensions are the planning doc's: RMP score and difficulty, grades,
   attendance, web vs F2F, Blinn vs College Station, honors, and the kinds of
   teacher a student asks for -- "less quizzes, easier tests, good lecturer".
2. **Ranking.** Those weights are applied to each candidate schedule, against
   structured data (ratings, difficulty, GPA, meeting times) and against traits
   Jev read out of the review text (``app/ingest/run_traits.py``).

The doc's own rule -- RMP score first, then difficulty -- stays the default and
the tiebreak, so a student who expresses no preference still gets what it asks
for. Preferences reorder within that, they do not replace it.

Every score comes with a breakdown, because "why is this one first" is the
question a schedule builder has to be able to answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.services.jev import DecisionSet, Question, choice, noul, score
from app.services.scheduling import DEFAULT_MIN_GAP_MINUTES, Schedule, Section

#: Three-level rubrics read better to a decision model than a 0-10 scale, and
#: the returned score is the expected value, so it still lands between levels.
HOW_MUCH = ("Not at all", "Somewhat", "A great deal")

#: What Jev is asked about the student's own words. Names become response keys.
PREFERENCE_QUESTIONS: dict[str, Question] = {
    "rating_importance": score(
        "How much does this student care about getting a highly rated professor?", HOW_MUCH
    ),
    "difficulty_aversion": score(
        "How much does this student want classes that are easy rather than challenging?",
        HOW_MUCH,
    ),
    "grade_importance": score(
        "How much does this student care about the grade distribution -- their odds of an A?",
        HOW_MUCH,
    ),
    "workload_aversion": score(
        "How much does this student want a light workload: fewer quizzes, less homework, "
        "fewer projects?",
        HOW_MUCH,
    ),
    "lecture_quality_importance": score(
        "How much does this student care about the professor being a good lecturer who "
        "explains the material clearly?",
        HOW_MUCH,
    ),
    "attendance_importance": score(
        "How much does this student want classes where attendance is not taken?", HOW_MUCH
    ),
    "avoid_early_mornings": noul(
        "Does this student want to avoid early-morning classes, before about 9:30am?"
    ),
    "avoid_fridays": noul("Does this student want to avoid Friday classes?"),
    "delivery": choice(
        "Which class format does this student prefer?",
        {
            "in_person": "Wants to attend in person, face to face",
            "online": "Wants online, web-based or remote classes",
            "either": "Has not expressed a preference either way",
        },
    ),
    "campus": choice(
        "Which campus does this student want to take classes at?",
        {
            "college_station": "Texas A&M's main College Station campus",
            "blinn": "Blinn College",
            "either": "Has not expressed a preference either way",
        },
    ),
    "gap_tolerance": choice(
        "How much time does this student want between back-to-back classes?",
        {
            "tight": "Does not mind rushing between classes; 20 minutes is fine",
            "comfortable": "Wants a comfortable walk; around 30 minutes",
            "relaxed": "Wants plenty of room; around 45 minutes",
            "long": "Wants a long break between classes; an hour or more",
        },
    ),
    "wants_honors": noul("Does this student want honors sections?"),
}

#: gap_tolerance -> minutes. Never below the doc's 20-minute floor.
GAP_MINUTES = {"tight": 20, "comfortable": 30, "relaxed": 45, "long": 60}


#: Above this, a yes/no answer counts as a stated wish rather than a shrug.
CLEAR_SIGNAL = 0.55


def _clear(value: float) -> float:
    return value if value > CLEAR_SIGNAL else 0.0


@dataclass(frozen=True, slots=True)
class Preferences:
    """Weights in 0-1, plus the hard filters."""

    rating: float = 0.5
    difficulty: float = 0.5
    grades: float = 0.5
    workload: float = 0.0
    lecture: float = 0.0
    attendance: float = 0.0
    avoid_early_mornings: float = 0.0
    avoid_fridays: float = 0.0
    delivery: str | None = None  # F2F | WEB | None
    campus: str | None = None  # CSTAT | BLINN | None
    honors: bool | None = None
    min_gap_minutes: int = DEFAULT_MIN_GAP_MINUTES
    #: Which model decided these, so the UI never implies a calibrated answer
    #: when it came from the keyword fallback.
    engine: str = "default"
    low_confidence: tuple[str, ...] = ()
    #: The student's own words, kept for display.
    stated: str | None = None

    @property
    def expressed(self) -> bool:
        """Whether anything beyond the defaults was asked for."""
        return self.engine != "default"

    @classmethod
    def from_decisions(cls, decisions: DecisionSet, *, stated: str | None = None) -> "Preferences":
        delivery = {"in_person": "F2F", "online": "WEB"}.get(
            decisions.chose("delivery", "either") or "either"
        )
        campus = {"college_station": "CSTAT", "blinn": "BLINN"}.get(
            decisions.chose("campus", "either") or "either"
        )
        gap = GAP_MINUTES.get(decisions.chose("gap_tolerance", "tight") or "tight", 20)
        return cls(
            rating=decisions.unit("rating_importance"),
            difficulty=decisions.unit("difficulty_aversion"),
            grades=decisions.unit("grade_importance"),
            workload=decisions.unit("workload_aversion"),
            lecture=decisions.unit("lecture_quality_importance"),
            attendance=decisions.unit("attendance_importance"),
            # An avoidance only counts when it is a clear yes. A noul of 0.5 is
            # the model declining to commit, and weighting that would quietly
            # push every student toward late, Friday-free weeks they never
            # asked for.
            avoid_early_mornings=_clear(decisions.unit("avoid_early_mornings", 0.0)),
            avoid_fridays=_clear(decisions.unit("avoid_fridays", 0.0)),
            delivery=delivery,
            campus=campus,
            honors=True if decisions.yes("wants_honors", 0.6) else None,
            min_gap_minutes=max(DEFAULT_MIN_GAP_MINUTES, gap),
            engine=decisions.model,
            low_confidence=decisions.low_confidence,
            stated=stated,
        )


@dataclass(frozen=True, slots=True)
class Traits:
    """What Jev read out of a professor's reviews. All 0-1, or None if unknown."""

    lots_of_quizzes: float | None = None
    exam_difficulty: float | None = None
    lecture_quality: float | None = None
    attendance_taken: float | None = None
    extra_credit: float | None = None
    heavy_workload: float | None = None
    grades_generously: float | None = None
    engine: str = "unknown"
    review_count: int = 0

    @classmethod
    def from_decisions(cls, decisions: DecisionSet, *, review_count: int = 0) -> "Traits":
        def maybe(name: str) -> float | None:
            return decisions.unit(name) if decisions.get(name) is not None else None

        return cls(
            lots_of_quizzes=maybe("lots_of_quizzes"),
            exam_difficulty=maybe("exam_difficulty"),
            lecture_quality=maybe("lecture_quality"),
            attendance_taken=maybe("attendance_taken"),
            extra_credit=maybe("extra_credit"),
            heavy_workload=maybe("heavy_workload"),
            grades_generously=maybe("grades_generously"),
            engine=decisions.model,
            review_count=review_count,
        )


#: What Jev is asked about a professor's review text. These are the doc's
#: "types of teachers and classes", and every one has a fixed answer set.
TRAIT_QUESTIONS: dict[str, Question] = {
    "lots_of_quizzes": noul(
        "Do these reviews say this professor gives frequent quizzes or pop quizzes?"
    ),
    "exam_difficulty": score(
        "How hard do these reviews say the exams and tests are?",
        ("Easy, straightforward", "Fair but demanding", "Very hard, tricky"),
    ),
    "lecture_quality": score(
        "How good a lecturer do these reviews say this professor is -- how clearly do "
        "they explain the material?",
        ("Poor, confusing", "Adequate", "Excellent, very clear"),
    ),
    "attendance_taken": noul("Do these reviews say attendance is required or taken?"),
    "extra_credit": noul("Do these reviews mention extra credit being offered?"),
    "heavy_workload": noul(
        "Do these reviews describe a heavy workload: lots of homework, projects or reading?"
    ),
    "grades_generously": noul(
        "Do these reviews say this professor grades generously, or curves grades upward?"
    ),
}

NO_TRAITS = Traits()


@dataclass(frozen=True, slots=True)
class Contribution:
    name: str
    weight: float
    value: float

    @property
    def points(self) -> float:
        return self.weight * self.value


@dataclass(frozen=True, slots=True)
class RankedSchedule:
    schedule: Schedule
    preference_score: float
    contributions: tuple[Contribution, ...]
    reasons: tuple[str, ...]

    @property
    def sort_key(self) -> tuple[float, float, float, int, int]:
        """Preference first, then the doc's rule, then less time wasted.

        Schedules built from the same instructors score identically on every
        preference about teaching, so the doc's rule ties too and the order
        among them was whatever the search happened to produce. Fewer days on
        campus and less waiting between classes break that deterministically,
        and are the difference a student would actually notice.
        """
        return (
            -self.preference_score,
            -self.schedule.mean_rating,
            self.schedule.mean_difficulty,
            self.schedule.days_on_campus,
            self.schedule.idle_minutes,
        )


def _mean(values: Sequence[float | None]) -> float | None:
    numbers = [v for v in values if v is not None]
    return sum(numbers) / len(numbers) if numbers else None


EARLY_CUTOFF = 9 * 60 + 30


def score_schedule(
    schedule: Schedule,
    preferences: Preferences,
    traits: Mapping[int, Traits] | None = None,
) -> RankedSchedule:
    """Score one schedule against what the student asked for.

    Each component is 0-1 and multiplied by its weight, so a dimension the
    student did not mention contributes nothing rather than quietly pulling the
    ranking around. Unknown data (a professor with no reviews) is skipped
    instead of being scored as zero, which would punish professors for our
    missing data.
    """
    traits = traits or {}
    per_section = [
        traits.get(s.instructor_id, NO_TRAITS) if s.instructor_id else NO_TRAITS
        for s in schedule.sections
    ]

    components: list[Contribution] = [
        Contribution("professor rating", preferences.rating, schedule.mean_rating / 5.0),
        Contribution(
            "easier classes", preferences.difficulty, 1.0 - schedule.mean_difficulty / 5.0
        ),
    ]
    if schedule.mean_gpa is not None:
        components.append(
            Contribution("grade distribution", preferences.grades, schedule.mean_gpa / 5.0)
        )

    lecture = _mean([t.lecture_quality for t in per_section])
    if lecture is not None:
        components.append(Contribution("good lecturers", preferences.lecture, lecture))

    workload = _mean(
        [
            v
            for t in per_section
            for v in (t.heavy_workload, t.lots_of_quizzes)
            if v is not None
        ]
    )
    if workload is not None:
        components.append(Contribution("light workload", preferences.workload, 1.0 - workload))

    attendance = _mean([t.attendance_taken for t in per_section])
    if attendance is not None:
        components.append(
            Contribution("attendance not taken", preferences.attendance, 1.0 - attendance)
        )

    # Format, campus and honors, when the student mentioned them. These rank
    # rather than exclude: an inferred preference that silently emptied the
    # results would be worse than one that merely sorted them.
    if preferences.delivery:
        matching = [
            1.0 if s.delivery is None or s.delivery == preferences.delivery else 0.0
            for s in schedule.sections
        ]
        components.append(
            Contribution(
                f"{'online' if preferences.delivery == 'WEB' else 'in person'} classes",
                1.0,
                sum(matching) / len(matching) if matching else 0.0,
            )
        )
    if preferences.campus:
        matching = [
            1.0 if s.campus is None or s.campus == preferences.campus else 0.0
            for s in schedule.sections
        ]
        components.append(
            Contribution("preferred campus", 1.0, sum(matching) / len(matching) if matching else 0.0)
        )
    if preferences.honors:
        matching = [1.0 if s.honors else 0.0 for s in schedule.sections]
        components.append(
            Contribution("honors sections", 1.0, sum(matching) / len(matching) if matching else 0.0)
        )

    if preferences.avoid_early_mornings > 0:
        late_enough = (
            1.0
            if schedule.earliest_start is None or schedule.earliest_start >= EARLY_CUTOFF
            else 0.0
        )
        components.append(
            Contribution("no early mornings", preferences.avoid_early_mornings, late_enough)
        )

    if preferences.avoid_fridays > 0:
        has_friday = any(m.day == "FRI" for s in schedule.sections for m in s.meetings)
        components.append(
            Contribution("no Friday classes", preferences.avoid_fridays, 0.0 if has_friday else 1.0)
        )

    weighted = [c for c in components if c.weight > 0]
    total = sum(c.points for c in weighted)
    divisor = sum(c.weight for c in weighted)
    normalized = total / divisor if divisor else 0.0

    # The reasons are the dimensions that actually earned this schedule its
    # place: heavily weighted and well satisfied.
    reasons = tuple(
        c.name
        for c in sorted(weighted, key=lambda c: c.points, reverse=True)
        if c.value >= 0.6
    )[:3]

    return RankedSchedule(
        schedule=schedule,
        preference_score=normalized,
        contributions=tuple(components),
        reasons=reasons,
    )


def rank(
    schedules: Sequence[Schedule],
    preferences: Preferences | None = None,
    traits: Mapping[int, Traits] | None = None,
) -> list[RankedSchedule]:
    """Rank schedules by preference, falling back to the doc's own rule.

    A student who expressed nothing gets the doc's ordering outright -- RMP
    score, then difficulty. The default weights are *defaults for display*, not
    an opinion to rank by, so applying them here would silently promote easy
    classes to someone who never asked for easy classes.
    """
    scored = [score_schedule(s, preferences or Preferences(), traits) for s in schedules]
    if preferences is None or not preferences.expressed:
        scored.sort(key=lambda r: r.schedule.sort_key)
    else:
        scored.sort(key=lambda r: r.sort_key)
    return scored


def section_matches(section: Section, preferences: Preferences) -> bool:
    """Hard filters, applied permissively where the data is unknown."""
    if preferences.delivery and section.delivery and section.delivery != preferences.delivery:
        return False
    if preferences.campus and section.campus and section.campus != preferences.campus:
        return False
    if preferences.honors is not None and section.honors != preferences.honors:
        return False
    return True
