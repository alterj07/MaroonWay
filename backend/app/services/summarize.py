"""Gemini comment summarisation.

Two summaries per professor, which is exactly what the planning doc asks for:

* **instructor-level** -- built from *all* of that professor's recent comments,
  describing general teaching style.
* **instructor+course-level** -- built only from comments tagged with that class
  code, describing what this specific class is like.

Output is structured, not prose: the frontend can render "attendance: mandatory"
as a chip without re-parsing English, and a rendered markdown blob rides along
for the body text.

Nothing here runs inside a request. Gemini's free tier is Flash/Flash-Lite only
(Pro went paid in April 2026) at roughly 10-30 requests per minute, so summaries
come from a resumable batch job (``app/ingest/run_summaries.py``) behind a token
bucket, and the API serves whatever Postgres already has.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.services.throttle import TokenBucket

#: Bump when a prompt or the schema changes -- it is part of the summary row's
#: unique key, so old summaries stay until regenerated and the batch job knows
#: what still needs doing.
PROMPT_VERSION = "v1"

INSTRUCTOR = "instructor"
INSTRUCTOR_COURSE = "instructor_course"

SYSTEM_INSTRUCTION = (
    "You summarise student reviews of university professors for other students "
    "choosing classes. Report only what the reviews actually say. Where reviews "
    "disagree, say so rather than averaging them. Never invent a detail that is "
    "not in the text, and never name individual students. Keep each field to one "
    "or two plain sentences."
)

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "Two sentences a student could skim."},
        "teaching_style": {"type": "string"},
        "workload": {"type": "string"},
        "exams": {"type": "string", "description": "Tests, quizzes, how grades are earned."},
        "attendance": {"type": "string", "enum": ["mandatory", "optional", "unclear"]},
        "extra_credit": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "pros": {"type": "array", "items": {"type": "string"}},
        "cons": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "string", "description": "Why this summary might mislead."},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["overview", "teaching_style", "workload", "exams", "confidence"],
}

FACET_LABELS = (
    ("teaching_style", "Teaching style"),
    ("workload", "Workload"),
    ("exams", "Exams and grading"),
)


@dataclass(frozen=True, slots=True)
class CommentInput:
    text: str
    class_code: str | None = None
    rated_at: datetime | None = None
    difficulty: float | None = None
    #: From the review itself, so the attendance and web-vs-F2F facets are
    #: grounded in structured data rather than inferred from prose.
    is_online: bool | None = None
    attendance_mandatory: bool | None = None


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    kind: str  # INSTRUCTOR | INSTRUCTOR_COURSE
    professor_name: str
    comments: Sequence[CommentInput]
    course_code: str | None = None
    term_labels: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.kind not in (INSTRUCTOR, INSTRUCTOR_COURSE):
            raise ValueError(f"unknown summary kind: {self.kind!r}")
        if self.kind == INSTRUCTOR_COURSE and not self.course_code:
            raise ValueError("a course-level summary needs a course_code")


@dataclass(slots=True)
class SummaryResult:
    facets: dict[str, Any]
    summary_md: str
    model: str
    prompt_version: str
    source_comment_count: int
    raw_text: str | None = None


def select_comments(
    comments: Iterable[CommentInput],
    *,
    limit: int,
    max_chars: int,
) -> list[CommentInput]:
    """Most recent first, capped and truncated -- the cost guard on each prompt."""
    usable = [c for c in comments if c.text and c.text.strip()]
    usable.sort(key=lambda c: (c.rated_at is not None, c.rated_at or datetime.min), reverse=True)
    trimmed: list[CommentInput] = []
    for comment in usable[: max(0, limit)]:
        text = comment.text.strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        trimmed.append(
            CommentInput(
                text,
                comment.class_code,
                comment.rated_at,
                comment.difficulty,
                comment.is_online,
                comment.attendance_mandatory,
            )
        )
    return trimmed


def build_prompt(request: SummaryRequest) -> str:
    """The user half of the prompt. Deterministic, so it is diffable in --dry-run."""
    if request.kind == INSTRUCTOR:
        head = (
            f"Summarise what students say about {request.professor_name} as an instructor, "
            "across all of their classes. Focus on general teaching style: how they lecture, "
            "how they treat students, how they run a course."
        )
    else:
        head = (
            f"Summarise what students say specifically about {request.professor_name}'s "
            f"{request.course_code} class. Describe this class, not the instructor in general: "
            "its workload, its tests, how it is graded."
        )

    terms = f" Reviews span {', '.join(request.term_labels)}." if request.term_labels else ""
    lines = [head + terms, "", f"Reviews ({len(request.comments)}):"]
    for index, comment in enumerate(request.comments, start=1):
        meta: list[str] = []
        if comment.class_code:
            meta.append(comment.class_code)
        if comment.rated_at:
            meta.append(comment.rated_at.date().isoformat())
        if comment.difficulty is not None:
            meta.append(f"difficulty {comment.difficulty:g}/5")
        if comment.is_online is not None:
            meta.append("online" if comment.is_online else "in person")
        if comment.attendance_mandatory is not None:
            meta.append(
                "attendance mandatory" if comment.attendance_mandatory else "attendance optional"
            )
        tag = f" [{'; '.join(meta)}]" if meta else ""
        lines.append(f"{index}.{tag} {comment.text}")
    return "\n".join(lines)


def render_markdown(facets: dict[str, Any]) -> str:
    """Render the structured facets into the body text the page shows."""
    parts: list[str] = []
    if overview := facets.get("overview"):
        parts.append(str(overview).strip())
    for key, label in FACET_LABELS:
        if value := facets.get(key):
            parts.append(f"**{label}.** {str(value).strip()}")
    for key, label in (("pros", "Students liked"), ("cons", "Students disliked")):
        items = facets.get(key) or []
        if isinstance(items, list) and items:
            bullets = "\n".join(f"- {str(item).strip()}" for item in items)
            parts.append(f"**{label}:**\n{bullets}")
    if caveat := facets.get("caveats"):
        parts.append(f"_{str(caveat).strip()}_")
    return "\n\n".join(parts)


class Summarizer(Protocol):
    async def summarize(self, request: SummaryRequest) -> SummaryResult: ...


class StubSummarizer:
    """Deterministic stand-in, so the whole pipeline is testable without a key."""

    model = "stub"

    def __init__(self) -> None:
        self.requests: list[SummaryRequest] = []

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        self.requests.append(request)
        subject = request.course_code or "this instructor"
        facets = {
            "overview": f"{len(request.comments)} reviews of {subject}.",
            "teaching_style": "stub",
            "workload": "stub",
            "exams": "stub",
            "attendance": "unclear",
            "extra_credit": "unclear",
            "pros": [],
            "cons": [],
            "caveats": "Generated by the stub summarizer.",
            "confidence": "low",
        }
        return SummaryResult(
            facets=facets,
            summary_md=render_markdown(facets),
            model=self.model,
            prompt_version=PROMPT_VERSION,
            source_comment_count=len(request.comments),
        )


def is_rate_limited(exc: BaseException) -> bool:
    """Whether an SDK error is a quota rejection worth backing off from."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "resource_exhausted" in text or "rate limit" in text


class GeminiSummarizer:
    """``google-genai`` client with backoff on 429.

    The model id comes from settings, never a literal: Google's free-tier model
    names have already shifted once this year.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        bucket: TokenBucket | None = None,
        max_attempts: int = 5,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        from google import genai  # imported here so the dep is optional at import time

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self._bucket = bucket or TokenBucket(10)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def verify_model(self) -> None:
        """Fail loudly at job start if the configured model is not reachable."""
        await self._client.aio.models.get(model=self.model)

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        prompt = build_prompt(request)
        last_error: BaseException | None = None

        for attempt in range(1, self._max_attempts + 1):
            await self._bucket.acquire()
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={
                        "system_instruction": SYSTEM_INSTRUCTION,
                        "response_mime_type": "application/json",
                        "response_schema": SUMMARY_SCHEMA,
                        "temperature": 0.2,
                    },
                )
            except BaseException as exc:  # noqa: BLE001 - classified below
                last_error = exc
                if not is_rate_limited(exc) or attempt == self._max_attempts:
                    raise
                backoff = min(60.0, 2.0**attempt) + random.uniform(0, 1.0)
                await self._sleep(backoff)
                continue

            facets = _parse_response(response)
            return SummaryResult(
                facets=facets,
                summary_md=render_markdown(facets),
                model=self.model,
                prompt_version=PROMPT_VERSION,
                source_comment_count=len(request.comments),
                raw_text=getattr(response, "text", None),
            )

        raise RuntimeError("summarize exhausted its retries") from last_error


def _parse_response(response: Any) -> dict[str, Any]:
    import json

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Gemini returned no text")
    return json.loads(text)


def estimate_tokens(prompt: str) -> int:
    """Rough count for --dry-run budgeting. ~4 characters per token."""
    return max(1, len(prompt) // 4)
