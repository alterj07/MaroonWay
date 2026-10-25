"""The decision layer: typed answers, not prose.

Jev is the reference implementation and the reason this layer exists, so it
leads. Two fallbacks live here too, behind the same ``Decider`` protocol --
Gemini with a response schema (free on the tier this project already uses) and
a keyword heuristic (free, crude, no key at all). Callers see ``Question`` and
``Decision`` and never learn which answered.


Jev is TypeSafe AI's "System One" decision model (released 15 Sep 2026). It is
*non-generative*: you send it state plus named, schema-constrained questions and
it answers in one pass with typed values and calibrated confidence. Three
question kinds matter here:

* ``noul``   -- a yes/no probability, 0 to 1.
* ``choice`` -- one of up to 255 named options, with a probability per option.
* ``score``  -- a position on an ordered rubric of 1-10 levels. The returned
  score is the probability-weighted expected value, so it can land between
  levels.

Verified against the installed ``typesafe-sdk`` (0.7.5) and docs.typesafe.ai:
``POST https://api.typesafe.ai/v1/systemone``, ``Authorization: Bearer <key>``,
request ``{model, state, questions}``, response ``{model, answers, usage}``,
default model ``jev-latest``, key from ``TYPESAFE_API_KEY``.

Why this and not an LLM: every question MaroonWay asks of review text has a
fixed answer set -- does this professor quiz often, how hard are the exams, is
attendance taken. A generative model would have to be asked for JSON and then
parsed and validated; Jev cannot answer off-schema, returns a confidence to
threshold on, bills input only, and answers in well under a second.

What it does *not* do is write, so the prose summaries stay with Gemini
(``app/services/summarize.py``). Jev decides; the LLM describes.

The SDK is kept at this boundary: the rest of the app sees ``Question`` and
``Decision``, so a provider change does not reach the routers.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.config import Settings

log = logging.getLogger("maroonway.jev")

NOUL, CHOICE, SCORE = "noul", "choice", "score"

#: Below this, the docs' own guidance is to escalate rather than act. We keep
#: the answer but mark it low-confidence so callers can fall back.
DEFAULT_CONFIDENCE_FLOOR = 0.45


@dataclass(frozen=True, slots=True)
class Question:
    """One question, in MaroonWay's terms rather than the SDK's."""

    kind: str
    instructions: str
    #: choice: {option: description}. score: ordered level labels. noul: unused.
    criteria: Mapping[str, str] | Sequence[str] | None = None

    def __post_init__(self) -> None:
        if self.kind not in (NOUL, CHOICE, SCORE):
            raise ValueError(f"unknown question kind: {self.kind!r}")
        if self.kind == CHOICE:
            if not isinstance(self.criteria, Mapping) or not 1 <= len(self.criteria) <= 255:
                raise ValueError("a choice needs 1 to 255 named options")
        if self.kind == SCORE:
            if not isinstance(self.criteria, Sequence) or not 1 <= len(self.criteria) <= 10:
                raise ValueError("a score needs an ordered rubric of 1 to 10 levels")


def noul(instructions: str) -> Question:
    return Question(NOUL, instructions)


def choice(instructions: str, options: Mapping[str, str]) -> Question:
    return Question(CHOICE, instructions, options)


def score(instructions: str, levels: Sequence[str]) -> Question:
    return Question(SCORE, instructions, tuple(levels))


@dataclass(frozen=True, slots=True)
class Decision:
    """One typed answer."""

    name: str
    kind: str
    #: noul -> probability 0-1; choice -> the chosen option; score -> expected level.
    value: Any
    confidence: float | None = None
    probabilities: Mapping[Any, float] | None = None
    levels: int | None = None  # score only, so value can be normalised

    @property
    def is_confident(self) -> bool:
        return self.confidence is None or self.confidence >= DEFAULT_CONFIDENCE_FLOOR

    def unit(self) -> float:
        """The answer as 0-1, whatever its kind -- which is what weighting needs.

        A score of 1.6 on a three-level rubric is 0.8 of the way up it; levels
        are zero-indexed, per the API.
        """
        if self.kind == NOUL:
            return max(0.0, min(float(self.value), 1.0))
        if self.kind == SCORE:
            top = (self.levels or 1) - 1
            return max(0.0, min(float(self.value) / top, 1.0)) if top > 0 else 0.0
        # A choice has no natural magnitude; its probability is the best proxy.
        if self.probabilities and self.value in self.probabilities:
            return float(self.probabilities[self.value])
        return 1.0


@dataclass(slots=True)
class DecisionSet:
    """Everything one call returned."""

    answers: dict[str, Decision] = field(default_factory=dict)
    model: str = "unknown"
    input_tokens: int | None = None

    def __getitem__(self, name: str) -> Decision:
        return self.answers[name]

    def get(self, name: str) -> Decision | None:
        return self.answers.get(name)

    def unit(self, name: str, default: float = 0.5) -> float:
        answer = self.answers.get(name)
        return answer.unit() if answer is not None else default

    def chose(self, name: str, default: str | None = None) -> str | None:
        answer = self.answers.get(name)
        return str(answer.value) if answer is not None and answer.kind == CHOICE else default

    def yes(self, name: str, threshold: float = 0.6) -> bool:
        """Whether a noul is a clear yes.

        The threshold is above 0.5 on purpose: an answer of exactly 0.5 is the
        model declining to commit, and reading that as "yes" turns a shrug into
        a filter.
        """
        answer = self.answers.get(name)
        return bool(answer is not None and answer.kind == NOUL and float(answer.value) >= threshold)

    @property
    def low_confidence(self) -> tuple[str, ...]:
        return tuple(name for name, a in self.answers.items() if not a.is_confident)


class Decider(Protocol):
    """Anything that can answer typed questions about some state."""

    model: str

    async def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionSet: ...


class JevDecider:
    """Jev through the official ``typesafe-sdk``."""

    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        kwargs: dict[str, Any] = {"api_key": api_key, "model": model}
        if base_url:
            kwargs["base_url"] = base_url
        if timeout:
            kwargs["timeout"] = timeout
        self._client = AsyncTypeSafeClient(**kwargs)
        self.model = model

    def _to_sdk(self, questions: Mapping[str, Question]) -> dict[str, Any]:
        from typesafe_sdk import Choice, Noul, Score

        built: dict[str, Any] = {}
        for name, question in questions.items():
            if question.kind == NOUL:
                built[name] = Noul(instructions=question.instructions)
            elif question.kind == CHOICE:
                built[name] = Choice(
                    instructions=question.instructions, criteria=dict(question.criteria or {})
                )
            else:
                built[name] = Score(
                    instructions=question.instructions, criteria=list(question.criteria or [])
                )
        return built

    async def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionSet:
        response = await self._client.system_one(state=state, questions=self._to_sdk(questions))
        answers: dict[str, Decision] = {}
        for name, answer in (getattr(response, "answers", None) or {}).items():
            kind = getattr(answer, "type", None)
            spec = questions.get(name)
            if kind == NOUL:
                answers[name] = Decision(name, NOUL, float(getattr(answer, "noul", 0.0)))
            elif kind == CHOICE:
                answers[name] = Decision(
                    name,
                    CHOICE,
                    getattr(answer, "choice", None),
                    confidence=getattr(answer, "confidence", None),
                    probabilities=dict(getattr(answer, "probabilities", {}) or {}),
                )
            elif kind == SCORE:
                answers[name] = Decision(
                    name,
                    SCORE,
                    float(getattr(answer, "score", 0.0)),
                    confidence=getattr(answer, "confidence", None),
                    probabilities=dict(getattr(answer, "probabilities", {}) or {}),
                    levels=len(spec.criteria) if spec and spec.criteria else None,
                )
        usage = getattr(response, "usage", None)
        return DecisionSet(
            answers=answers,
            model=str(getattr(response, "model", self.model)),
            input_tokens=getattr(usage, "input_tokens", None),
        )


class HeuristicDecider:
    """A keyword fallback for when no API key is configured.

    Deliberately not a pretend Jev: it reports ``model="heuristic"`` so every
    response says which engine decided, and it answers from literal keyword
    matches against the state. Good enough to keep the product usable and the
    tests honest; not good enough to be mistaken for a calibrated model.
    """

    model = "heuristic"

    #: question name -> words whose presence raises the answer.
    KEYWORDS: dict[str, tuple[str, ...]] = {
        "rating_importance": ("good professor", "great teacher", "best professor", "rating", "well rated"),
        "difficulty_aversion": ("easy", "easier", "light", "chill", "gpa boost", "not hard", "manageable"),
        "grade_importance": ("easy a", "good grade", "gpa", "a's", "high grade"),
        "workload_aversion": ("less homework", "less work", "quizzes", "light workload", "less reading", "fewer projects"),
        "lecture_quality_importance": ("good lecturer", "lecture", "explains", "teaching", "clear"),
        "attendance_importance": ("attendance", "mandatory"),
        "wants_honors": ("honors",),
    }

    #: question name -> the thing the student may be asking to avoid. Matched
    #: with a negation ("no", "avoid", "without") nearby, because "no early
    #: classes" and "I'm an early bird" share the word that matters.
    AVOIDS: dict[str, tuple[str, ...]] = {
        "avoid_early_mornings": ("early", "morning", "8am", "8 am", "8:00"),
        "avoid_fridays": ("friday",),
    }

    _NEGATION = re.compile(
        r"\b(no|not|non|none|nothing|avoid|without|skip|never|hate|rather not"
        r"|don'?t want|free of)\b"
    )

    def _avoided(self, text: str, words: tuple[str, ...]) -> float:
        """Whether the student asked to avoid any of these, 0-1."""
        for word in words:
            for match in re.finditer(re.escape(word), text):
                window = text[max(0, match.start() - 28) : match.start()]
                if self._NEGATION.search(window):
                    return 0.9
        return 0.1 if any(word in text for word in words) else 0.5

    def __init__(self, *, floor: float = 0.5) -> None:
        self._floor = floor

    async def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionSet:
        text = (state if isinstance(state, str) else repr(state)).lower()
        answers: dict[str, Decision] = {}
        for name, question in questions.items():
            if name in self.AVOIDS:
                strength = self._avoided(text, self.AVOIDS[name])
            else:
                words = self.KEYWORDS.get(name, ())
                hits = sum(1 for word in words if word in text)
                strength = max(0.0, min(0.5 + 0.25 * hits, 1.0)) if words else 0.5

            if question.kind == NOUL:
                answers[name] = Decision(name, NOUL, strength, confidence=0.3)
            elif question.kind == CHOICE:
                options = list(question.criteria or {})
                picked = next(
                    (
                        opt
                        for opt in options
                        if re.search(rf"\b{re.escape(opt.replace('_', ' '))}\b", text)
                    ),
                    None,
                )
                if picked is None:
                    # Default to the least constraining option, not whichever
                    # happens to be last: an unstated gap preference becoming
                    # "an hour between classes" would rule out real schedules.
                    picked = "either" if "either" in options else (options[0] if options else None)
                answers[name] = Decision(
                    name, CHOICE, picked, confidence=0.3,
                    probabilities={opt: (1.0 if opt == picked else 0.0) for opt in options},
                )
            else:
                levels = len(question.criteria or [1])
                answers[name] = Decision(
                    name, SCORE, strength * (levels - 1), confidence=0.3, levels=levels
                )
        return DecisionSet(answers=answers, model=self.model)


class GeminiDecider:
    """Gemini, constrained to the same typed answers.

    Not a decision model: it is generative, so it has to be *asked* for a shape
    and the shape has to be enforced. ``response_schema`` does that -- an enum
    per choice question, a bounded number per noul, a level index per score --
    which gets back the one property that makes Jev usable here. What it does
    not get back is a calibrated confidence: Gemini's self-reported number is
    not a probability, so it is recorded but never thresholded on, and the
    engine name says which model answered.

    Free on the tier this project already uses for summaries, which is the
    reason it exists.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-flash-lite-latest",
        *,
        rpm: float = 10.0,
        sleep: Any = None,
    ) -> None:
        from google import genai

        from app.services.throttle import TokenBucket

        self._client = genai.Client(api_key=api_key)
        self.model = f"gemini:{model}"
        self._model_id = model
        self._bucket = TokenBucket(rpm) if sleep is None else TokenBucket(rpm, sleep=sleep)

    @staticmethod
    def _schema(questions: Mapping[str, Question]) -> dict[str, Any]:
        """One JSON object, one property per question, values pinned."""
        properties: dict[str, Any] = {}
        for name, question in questions.items():
            if question.kind == NOUL:
                properties[name] = {
                    "type": "object",
                    "properties": {
                        "noul": {
                            "type": "number",
                            "description": "Probability of yes, 0 to 1",
                        }
                    },
                    "required": ["noul"],
                }
            elif question.kind == CHOICE:
                properties[name] = {
                    "type": "object",
                    "properties": {
                        "choice": {"type": "string", "enum": list(question.criteria or {})},
                        "confidence": {"type": "number"},
                    },
                    "required": ["choice"],
                }
            else:
                levels = len(question.criteria or [])
                properties[name] = {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": f"0 to {max(levels - 1, 0)}, where 0 is the first level",
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["level"],
                }
        return {"type": "object", "properties": properties, "required": list(properties)}

    @staticmethod
    def _prompt(state: Any, questions: Mapping[str, Question]) -> str:
        lines = [
            "Answer each question about the state below. Use only the allowed "
            "values. Report what the state actually says; where it says nothing "
            "about a question, answer neutrally rather than guessing.",
            "",
            "Questions:",
        ]
        for name, question in questions.items():
            lines.append(f"- {name} ({question.kind}): {question.instructions}")
            if question.kind == CHOICE and question.criteria:
                for option, description in question.criteria.items():
                    lines.append(f"    {option}: {description}")
            elif question.kind == SCORE and question.criteria:
                for index, level in enumerate(question.criteria):
                    lines.append(f"    {index} = {level}")
        lines += ["", "State:", state if isinstance(state, str) else json.dumps(state, default=str)]
        return "\n".join(lines)

    async def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionSet:
        await self._bucket.acquire()
        response = await self._client.aio.models.generate_content(
            model=self._model_id,
            contents=self._prompt(state, questions),
            config={
                "response_mime_type": "application/json",
                "response_schema": self._schema(questions),
                "temperature": 0.0,
            },
        )
        raw = getattr(response, "parsed", None)
        if not isinstance(raw, dict):
            raw = json.loads(getattr(response, "text", None) or "{}")

        answers: dict[str, Decision] = {}
        for name, question in questions.items():
            given = raw.get(name)
            if not isinstance(given, dict):
                continue
            # Recorded, never thresholded on: a generative model's self-reported
            # confidence is not a calibrated probability.
            confidence = given.get("confidence")
            if question.kind == NOUL:
                answers[name] = Decision(
                    name, NOUL, max(0.0, min(float(given.get("noul", 0.5)), 1.0))
                )
            elif question.kind == CHOICE:
                picked = given.get("choice")
                if picked in (question.criteria or {}):
                    answers[name] = Decision(name, CHOICE, picked, confidence=confidence)
            else:
                levels = len(question.criteria or [])
                level = int(given.get("level", 0))
                answers[name] = Decision(
                    name,
                    SCORE,
                    float(max(0, min(level, max(levels - 1, 0)))),
                    confidence=confidence,
                    levels=levels,
                )
        usage = getattr(response, "usage_metadata", None)
        return DecisionSet(
            answers=answers,
            model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", None),
        )


def build_decider(settings: "Settings") -> Decider:
    """The best engine the configuration allows.

    Jev first, because it is the only one here that is actually a decision
    model. Gemini next, because it is free on the tier this project already
    uses and ``response_schema`` keeps answers on-schema. The keyword heuristic
    last, so the product still works with no keys at all.
    """
    if settings.typesafe_api_key:
        return JevDecider(
            settings.typesafe_api_key, settings.jev_model, base_url=settings.jev_base_url
        )
    if settings.gemini_api_key:
        log.info(
            "TYPESAFE_API_KEY is unset; deciding with Gemini (%s). Free, but "
            "slower than Jev and without a calibrated confidence.",
            settings.gemini_model,
        )
        return GeminiDecider(
            settings.gemini_api_key, settings.gemini_model, rpm=settings.summary_rpm
        )
    log.warning(
        "no TYPESAFE_API_KEY or GEMINI_API_KEY -- falling back to keyword "
        "heuristics. Decisions will be crude and are reported as "
        "model=heuristic so nothing presents them as calibrated."
    )
    return HeuristicDecider()
