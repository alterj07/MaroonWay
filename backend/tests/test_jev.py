"""The Jev decision layer and the preference weighting it produces.

Jev itself is not called here. What is tested is the boundary: that our
questions are well formed, that its typed answers become weights correctly, and
that the ranking does what the planning doc asks.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.jev import (
    CHOICE,
    NOUL,
    SCORE,
    Decision,
    DecisionSet,
    HeuristicDecider,
    Question,
    build_decider,
    choice,
    noul,
    score,
)
from app.services.preferences import (
    GAP_MINUTES,
    PREFERENCE_QUESTIONS,
    TRAIT_QUESTIONS,
    Preferences,
    Traits,
    rank,
    score_schedule,
    section_matches,
)
from app.services.scheduling import DEFAULT_MIN_GAP_MINUTES, summarize
from tests.test_scheduling import section


# --- question construction ----------------------------------------------------


def test_a_choice_needs_options():
    with pytest.raises(ValueError):
        Question(CHOICE, "pick one")


def test_a_choice_is_capped_at_the_api_s_255_options():
    with pytest.raises(ValueError):
        choice("pick", {str(i): str(i) for i in range(256)})


def test_a_score_rubric_is_capped_at_ten_levels():
    with pytest.raises(ValueError):
        score("rate", [f"level {i}" for i in range(11)])


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        Question("vibes", "how do you feel")


def test_every_preference_and_trait_question_is_valid():
    """Construction validates, so merely building them is the assertion."""
    assert len(PREFERENCE_QUESTIONS) == 12
    assert len(TRAIT_QUESTIONS) == 7
    assert all(q.kind in (NOUL, CHOICE, SCORE) for q in PREFERENCE_QUESTIONS.values())


def test_the_trait_questions_cover_the_doc_s_wants():
    """"less quizzes, easier tests, good lecturer", attendance, extra credit."""
    assert {"lots_of_quizzes", "exam_difficulty", "lecture_quality"} <= set(TRAIT_QUESTIONS)
    assert {"attendance_taken", "extra_credit"} <= set(TRAIT_QUESTIONS)


# --- normalising answers ------------------------------------------------------


def test_a_noul_is_already_a_probability():
    assert Decision("x", NOUL, 0.8).unit() == pytest.approx(0.8)


def test_a_score_normalises_against_its_rubric():
    """Levels are zero-indexed, so 1.6 of 3 levels is 0.8 of the way up."""
    assert Decision("x", SCORE, 1.6, levels=3).unit() == pytest.approx(0.8)
    assert Decision("x", SCORE, 0.0, levels=3).unit() == 0.0
    assert Decision("x", SCORE, 2.0, levels=3).unit() == 1.0


def test_a_choice_uses_its_own_probability_as_magnitude():
    answer = Decision("x", CHOICE, "online", probabilities={"online": 0.7, "in_person": 0.3})
    assert answer.unit() == pytest.approx(0.7)


def test_low_confidence_answers_are_flagged_not_discarded():
    confident = Decision("a", CHOICE, "x", confidence=0.9)
    shaky = Decision("b", CHOICE, "y", confidence=0.1)
    decisions = DecisionSet({"a": confident, "b": shaky}, model="jev-1.14")

    assert confident.is_confident and not shaky.is_confident
    assert decisions.low_confidence == ("b",)
    assert decisions.chose("b") == "y", "still usable, just marked"


def test_accessors_tolerate_a_missing_answer():
    decisions = DecisionSet({}, model="jev-1.14")
    assert decisions.get("nope") is None
    assert decisions.unit("nope", 0.25) == 0.25
    assert decisions.chose("nope", "fallback") == "fallback"
    assert decisions.yes("nope") is False


# --- preferences from answers -------------------------------------------------


def answers(**raw) -> DecisionSet:
    built: dict[str, Decision] = {}
    for name, value in raw.items():
        question = PREFERENCE_QUESTIONS[name]
        if question.kind == NOUL:
            built[name] = Decision(name, NOUL, value)
        elif question.kind == CHOICE:
            built[name] = Decision(name, CHOICE, value, confidence=0.9)
        else:
            levels = len(question.criteria)
            built[name] = Decision(name, SCORE, value * (levels - 1), confidence=0.9, levels=levels)
    return DecisionSet(built, model="jev-1.14")


def test_weights_come_through_normalised():
    prefs = Preferences.from_decisions(answers(rating_importance=1.0, difficulty_aversion=0.5))
    assert prefs.rating == pytest.approx(1.0)
    assert prefs.difficulty == pytest.approx(0.5)
    assert prefs.engine == "jev-1.14"


def test_choices_map_onto_the_database_s_values():
    prefs = Preferences.from_decisions(answers(delivery="online", campus="blinn"))
    assert prefs.delivery == "WEB"
    assert prefs.campus == "BLINN"


def test_either_means_no_filter():
    prefs = Preferences.from_decisions(answers(delivery="either", campus="either"))
    assert prefs.delivery is None
    assert prefs.campus is None


def test_gap_tolerance_becomes_minutes_and_never_goes_under_the_floor():
    assert GAP_MINUTES["tight"] == DEFAULT_MIN_GAP_MINUTES
    for option, minutes in GAP_MINUTES.items():
        prefs = Preferences.from_decisions(answers(gap_tolerance=option))
        assert prefs.min_gap_minutes == max(DEFAULT_MIN_GAP_MINUTES, minutes)
        assert prefs.min_gap_minutes >= DEFAULT_MIN_GAP_MINUTES


def test_honors_is_only_a_filter_when_asked_for():
    assert Preferences.from_decisions(answers(wants_honors=0.9)).honors is True
    assert Preferences.from_decisions(answers(wants_honors=0.1)).honors is None


def test_default_preferences_are_marked_as_not_expressed():
    assert Preferences().expressed is False
    assert Preferences.from_decisions(answers(rating_importance=1.0)).expressed is True


# --- ranking ------------------------------------------------------------------


def schedule_of(*sections):
    return summarize(list(sections))


def test_with_no_preferences_the_doc_s_rule_still_decides():
    """RMP score first, then difficulty."""
    good = schedule_of(section("A", rating=4.8, difficulty=4.0))
    easy = schedule_of(section("B", rating=4.0, difficulty=2.0))
    ranked = rank([easy, good])
    assert ranked[0].schedule is good


def test_a_student_who_wants_easy_gets_easy_first():
    good = schedule_of(section("A", rating=4.8, difficulty=4.5))
    easy = schedule_of(section("B", rating=4.0, difficulty=1.5))
    ranked = rank([good, easy], Preferences(rating=0.0, difficulty=1.0, grades=0.0, engine="jev"))
    assert ranked[0].schedule is easy


def test_an_unweighted_dimension_contributes_nothing():
    prefs = Preferences(rating=1.0, difficulty=0.0, grades=0.0, engine="jev")
    result = score_schedule(schedule_of(section("A", rating=5.0, difficulty=5.0)), prefs)
    assert result.preference_score == pytest.approx(1.0)


def test_avoiding_fridays_ranks_a_friday_free_week_first():
    mwf = schedule_of(section("A", days="MWF", rating=4.5, difficulty=3.0))
    tr = schedule_of(section("B", days="TR", rating=4.5, difficulty=3.0))
    prefs = Preferences(rating=0.2, difficulty=0.0, grades=0.0, avoid_fridays=1.0, engine="jev")
    ranked = rank([mwf, tr], prefs)

    assert ranked[0].schedule is tr
    assert "no Friday classes" in ranked[0].reasons


def test_avoiding_early_mornings_ranks_the_later_start_first():
    early = schedule_of(section("A", start="08:00", end="08:50", rating=4.5))
    late = schedule_of(section("B", start="11:30", end="12:20", rating=4.5))
    prefs = Preferences(
        rating=0.2, difficulty=0.0, grades=0.0, avoid_early_mornings=1.0, engine="jev"
    )
    assert rank([early, late], prefs)[0].schedule is late


def test_traits_from_jev_drive_the_workload_preference():
    quizzy = section("A", rating=4.5, difficulty=3.0)
    calm = section("B", rating=4.5, difficulty=3.0)
    traits = {
        (quizzy.instructor_id, None): Traits(heavy_workload=1.0, lots_of_quizzes=1.0, engine="jev-1.14"),
    }
    prefs = Preferences(rating=0.1, difficulty=0.0, grades=0.0, workload=1.0, engine="jev")

    # Same instructor id on both helpers, so score them separately.
    heavy = score_schedule(schedule_of(quizzy), prefs, traits)
    light = score_schedule(schedule_of(calm), prefs, {})
    assert heavy.preference_score < light.preference_score


def test_a_professor_with_no_reviews_is_not_punished_for_our_missing_data():
    prefs = Preferences(rating=0.5, difficulty=0.0, grades=0.0, lecture=1.0, engine="jev")
    result = score_schedule(schedule_of(section("A", rating=4.0)), prefs, {})
    # Lecture quality is unknown, so it is skipped rather than scored zero.
    assert [c.name for c in result.contributions] == ["professor rating", "easier classes"]


@pytest.mark.parametrize("traits, expected_quality", [
    ({(7, None): Traits(lecture_quality=0.4), (7, 1): Traits(lecture_quality=0.9)}, 0.9),
    ({(7, None): Traits(lecture_quality=0.4), (7, 2): Traits(lecture_quality=0.1)}, 0.4),
    ({(7, None): Traits(lecture_quality=0.4), (7, 1): Traits()}, None),
    ({(7, 2): Traits(lecture_quality=0.1)}, None),
    ({(8, 1): Traits(lecture_quality=0.9)}, None),
])
def test_lecture_traits_use_the_exact_course_then_general_professor_notes(traits, expected_quality):
    candidate = replace(section("A"), instructor_id=7, course_id=1)
    result = score_schedule(schedule_of(candidate), Preferences(lecture=1.0), traits)
    lecture = [c for c in result.contributions if c.name == "good lecturers"]
    if expected_quality is None:
        assert lecture == []
    else:
        assert len(lecture) == 1
        assert lecture[0].value == pytest.approx(expected_quality)


def test_ranking_uses_each_courses_own_notes_for_the_same_professor():
    good = schedule_of(replace(section("A"), instructor_id=7, course_id=1))
    poor = schedule_of(replace(section("B"), instructor_id=7, course_id=2))
    traits = {(7, 1): Traits(lecture_quality=0.9), (7, 2): Traits(lecture_quality=0.1)}
    ranked = rank([poor, good], Preferences(rating=0, difficulty=0, grades=0, lecture=1, engine="test"), traits)
    assert ranked[0].schedule is good


def test_reasons_name_what_earned_the_place():
    prefs = Preferences(rating=1.0, difficulty=0.0, grades=0.0, engine="jev")
    result = score_schedule(schedule_of(section("A", rating=4.8)), prefs)
    assert "professor rating" in result.reasons


# --- hard filters -------------------------------------------------------------


def test_delivery_and_campus_filters():
    online = section("A", online=True)
    prefs = Preferences(delivery="WEB", engine="jev")
    assert section_matches(online, prefs)
    assert not section_matches(section("B", delivery="F2F"), prefs)


def test_a_filter_does_not_exclude_a_section_whose_data_is_unknown():
    """Hiding a real class over missing metadata is worse than showing it."""
    unknown = section("A", campus=None, delivery=None)
    assert section_matches(unknown, Preferences(campus="CSTAT", delivery="WEB", engine="jev"))


def test_honors_filters_both_ways():
    assert section_matches(section("A", honors=True), Preferences(honors=True, engine="jev"))
    assert not section_matches(section("A", honors=False), Preferences(honors=True, engine="jev"))


# --- the fallback -------------------------------------------------------------


async def test_the_heuristic_fallback_answers_every_question_shape():
    decisions = await HeuristicDecider().decide(
        "I want easy A's with no 8am classes and a good lecturer", PREFERENCE_QUESTIONS
    )
    assert set(decisions.answers) == set(PREFERENCE_QUESTIONS)
    assert decisions.model == "heuristic", "never claims to be Jev"


async def test_the_fallback_reads_obvious_wants():
    decisions = await HeuristicDecider().decide(
        "please no early morning classes and nothing on friday", PREFERENCE_QUESTIONS
    )
    prefs = Preferences.from_decisions(decisions)
    assert prefs.avoid_early_mornings > 0.5
    assert prefs.avoid_fridays > 0.5


async def test_the_fallback_marks_itself_low_confidence():
    decisions = await HeuristicDecider().decide("anything", PREFERENCE_QUESTIONS)
    assert decisions.low_confidence, "a keyword guess must not look calibrated"


def settings_with(**overrides):
    from app.config import Settings

    base = {
        "database_url": "postgresql+asyncpg://unused/unused",
        "typesafe_api_key": None,
        "gemini_api_key": None,
    }
    return Settings(**{**base, **overrides})


def test_build_decider_prefers_jev(monkeypatch):
    built: dict[str, object] = {}

    class FakeJev:
        model = "jev-latest"

        def __init__(self, key, model, *, base_url=None):
            built["key"] = key

    monkeypatch.setattr("app.services.jev.JevDecider", FakeJev)
    decider = build_decider(settings_with(typesafe_api_key="sk-x", gemini_api_key="g"))
    assert isinstance(decider, FakeJev)
    assert built["key"] == "sk-x", "Jev wins when both keys are present"


def test_build_decider_uses_gemini_when_jev_is_absent(monkeypatch):
    class FakeGemini:
        model = "gemini:flash"

        def __init__(self, key, model, *, rpm=10.0):
            pass

    monkeypatch.setattr("app.services.jev.GeminiDecider", FakeGemini)
    assert isinstance(build_decider(settings_with(gemini_api_key="g")), FakeGemini)


def test_build_decider_falls_back_with_no_keys():
    assert build_decider(settings_with()).model == "heuristic"


# --- the Gemini decider's schema and parsing ----------------------------------


def gemini_decider(response):
    """A GeminiDecider wired to a fake client, so no network and no key."""
    from app.services.jev import GeminiDecider

    decider = GeminiDecider.__new__(GeminiDecider)
    decider.model = "gemini:test"
    decider._model_id = "test"

    class Bucket:
        async def acquire(self):
            return 0.0

    class Models:
        def __init__(self):
            self.config = None

        async def generate_content(self, *, model, contents, config):
            self.config = config
            self.contents = contents
            return response

    client = type("Client", (), {})()
    client.aio = type("Aio", (), {})()
    client.aio.models = Models()
    decider._client = client
    decider._bucket = Bucket()
    return decider


def test_the_gemini_schema_pins_every_answer():
    from app.services.jev import GeminiDecider

    schema = GeminiDecider._schema(
        {
            "a": noul("yes or no?"),
            "b": choice("which?", {"x": "the x", "y": "the y"}),
            "c": score("how much?", ("low", "mid", "high")),
        }
    )

    assert schema["required"] == ["a", "b", "c"]
    assert schema["properties"]["b"]["properties"]["choice"]["enum"] == ["x", "y"]
    assert "0 to 2" in schema["properties"]["c"]["properties"]["level"]["description"]


async def test_gemini_answers_are_mapped_to_decisions():
    class Response:
        parsed = {
            "a": {"noul": 0.8},
            "b": {"choice": "y", "confidence": 0.6},
            "c": {"level": 2, "confidence": 0.7},
        }
        text = "{}"

    decider = gemini_decider(Response())
    decisions = await decider.decide(
        "some state",
        {
            "a": noul("yes or no?"),
            "b": choice("which?", {"x": "the x", "y": "the y"}),
            "c": score("how much?", ("low", "mid", "high")),
        },
    )

    assert decisions.model == "gemini:test"
    assert decisions["a"].unit() == pytest.approx(0.8)
    assert decisions["b"].value == "y"
    assert decisions["c"].unit() == pytest.approx(1.0), "level 2 of 3 is the top"


async def test_gemini_rejects_a_choice_outside_the_schema():
    """Belt and braces: response_schema should prevent it, but a value that is
    not an option must never become an answer."""

    class Response:
        parsed = {"b": {"choice": "something_else"}}
        text = "{}"

    decisions = await gemini_decider(Response()).decide(
        "state", {"b": choice("which?", {"x": "the x", "y": "the y"})}
    )
    assert decisions.get("b") is None


async def test_gemini_falls_back_to_parsing_the_text():
    class Response:
        parsed = None
        text = '{"a": {"noul": 0.25}}'

    decisions = await gemini_decider(Response()).decide("state", {"a": noul("yes?")})
    assert decisions["a"].unit() == pytest.approx(0.25)


async def test_gemini_clamps_an_out_of_range_answer():
    class Response:
        parsed = {"a": {"noul": 7.5}, "c": {"level": 99}}
        text = "{}"

    decisions = await gemini_decider(Response()).decide(
        "state", {"a": noul("yes?"), "c": score("how much?", ("low", "mid", "high"))}
    )
    assert decisions["a"].unit() == 1.0
    assert decisions["c"].value == 2.0


async def test_the_gemini_prompt_lists_the_allowed_values():
    class Response:
        parsed = {}
        text = "{}"

    decider = gemini_decider(Response())
    await decider.decide(
        {"reviews": ["tough grader"]},
        {"c": score("how hard?", ("easy", "fair", "brutal"))},
    )
    prompt = decider._client.aio.models.contents
    assert "0 = easy" in prompt and "2 = brutal" in prompt
    assert "tough grader" in prompt



async def test_an_unstated_choice_defaults_to_the_least_constraining_option():
    """An unmentioned gap preference must not become an hour between classes,
    and an unmentioned campus must not become a filter."""
    decisions = await HeuristicDecider().decide("I want good professors", PREFERENCE_QUESTIONS)
    prefs = Preferences.from_decisions(decisions)

    assert prefs.min_gap_minutes == DEFAULT_MIN_GAP_MINUTES
    assert prefs.campus is None
    assert prefs.delivery is None


async def test_an_unmentioned_avoidance_carries_no_weight():
    """A noul of 0.5 is the model declining to commit. Weighting it would push
    every student toward late, Friday-free weeks they never asked for."""
    decisions = await HeuristicDecider().decide(
        "I want the very best professors, I do not care how hard it is",
        PREFERENCE_QUESTIONS,
    )
    prefs = Preferences.from_decisions(decisions)

    assert prefs.avoid_early_mornings == 0.0
    assert prefs.avoid_fridays == 0.0
    assert prefs.rating > 0, "what they did say still counts"


def test_a_stated_avoidance_does_carry_weight():
    prefs = Preferences.from_decisions(answers(avoid_fridays=0.9, avoid_early_mornings=0.9))
    assert prefs.avoid_fridays == pytest.approx(0.9)
    assert prefs.avoid_early_mornings == pytest.approx(0.9)
