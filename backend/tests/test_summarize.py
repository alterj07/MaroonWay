"""Prompt construction, comment selection, throttling, and 429 backoff."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.summarize import (
    INSTRUCTOR,
    INSTRUCTOR_COURSE,
    PROMPT_VERSION,
    CommentInput,
    GeminiSummarizer,
    StubSummarizer,
    SummaryRequest,
    build_prompt,
    estimate_tokens,
    is_rate_limited,
    render_markdown,
    select_comments,
)
from app.services.throttle import TokenBucket


def utc(year: int, month: int, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def comment(text: str, *, code: str = "CSCE121", when: datetime | None = None) -> CommentInput:
    return CommentInput(text, code, when or utc(2025, 9))


def test_a_course_summary_requires_a_course_code():
    with pytest.raises(ValueError):
        SummaryRequest(kind=INSTRUCTOR_COURSE, professor_name="A", comments=[])


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        SummaryRequest(kind="vibes", professor_name="A", comments=[])


def test_comments_are_capped_newest_first():
    comments = [comment(f"c{i}", when=utc(2020 + i, 1)) for i in range(6)]
    picked = select_comments(comments, limit=3, max_chars=100)
    assert [c.text for c in picked] == ["c5", "c4", "c3"]


def test_long_comments_are_truncated_with_an_ellipsis():
    picked = select_comments([comment("x" * 50)], limit=5, max_chars=20)
    assert len(picked[0].text) == 20
    assert picked[0].text.endswith("…")


def test_blank_comments_are_dropped():
    assert select_comments([comment("  "), comment("real")], limit=5, max_chars=50) == [
        CommentInput("real", "CSCE121", utc(2025, 9), None, None, None)
    ]


def test_undated_comments_sort_last_but_survive():
    picked = select_comments(
        [CommentInput("undated"), comment("dated")], limit=5, max_chars=50
    )
    assert [c.text for c in picked] == ["dated", "undated"]


def test_instructor_prompt_asks_about_general_style():
    prompt = build_prompt(
        SummaryRequest(
            kind=INSTRUCTOR,
            professor_name="Jane Doe",
            comments=[comment("Great lecturer.")],
            term_labels=["Fall 2025"],
        )
    )
    assert "across all of their classes" in prompt
    assert "general teaching style" in prompt
    assert "Fall 2025" in prompt
    assert "Great lecturer." in prompt


def test_course_prompt_asks_about_this_class_only():
    prompt = build_prompt(
        SummaryRequest(
            kind=INSTRUCTOR_COURSE,
            professor_name="Jane Doe",
            course_code="CSCE121",
            comments=[comment("Hard tests.")],
        )
    )
    assert "CSCE121" in prompt
    assert "not the instructor in general" in prompt


def test_prompt_carries_attendance_and_delivery_metadata():
    prompt = build_prompt(
        SummaryRequest(
            kind=INSTRUCTOR,
            professor_name="Jane Doe",
            comments=[
                CommentInput("online class", "CSCE121", utc(2025, 9), 2.0, True, False),
            ],
        )
    )
    assert "online" in prompt
    assert "attendance optional" in prompt


def test_prompts_are_deterministic():
    request = SummaryRequest(
        kind=INSTRUCTOR, professor_name="Jane Doe", comments=[comment("Same.")]
    )
    assert build_prompt(request) == build_prompt(request)


def test_rendered_markdown_includes_facets_and_bullets():
    rendered = render_markdown(
        {
            "overview": "Clear lecturer.",
            "teaching_style": "Lectures from slides.",
            "workload": "Weekly homework.",
            "exams": "Three exams.",
            "pros": ["Responsive"],
            "cons": ["Fast pace"],
            "caveats": "Only nine reviews.",
        }
    )
    assert "Clear lecturer." in rendered
    assert "**Teaching style.** Lectures from slides." in rendered
    assert "- Responsive" in rendered
    assert "_Only nine reviews._" in rendered


def test_rendered_markdown_skips_missing_fields():
    assert render_markdown({"overview": "Only this."}) == "Only this."
    assert render_markdown({}) == ""


async def test_stub_summarizer_round_trips():
    summarizer = StubSummarizer()
    result = await summarizer.summarize(
        SummaryRequest(kind=INSTRUCTOR, professor_name="Jane", comments=[comment("ok")])
    )
    assert result.prompt_version == PROMPT_VERSION
    assert result.source_comment_count == 1
    assert result.summary_md
    assert summarizer.requests  # it recorded the call, so jobs are inspectable


async def test_token_bucket_paces_requests():
    now = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    bucket = TokenBucket(60, clock=lambda: now[0], sleep=sleep)  # one per second
    assert await bucket.acquire() == 0.0
    assert await bucket.acquire() == pytest.approx(1.0)
    assert await bucket.acquire() == pytest.approx(1.0)
    assert waits == [pytest.approx(1.0), pytest.approx(1.0)]


async def test_token_bucket_with_no_limit_never_waits():
    bucket = TokenBucket(0)
    assert await bucket.acquire() == 0.0


def test_rate_limit_detection():
    assert is_rate_limited(Exception("429 Too Many Requests"))
    assert is_rate_limited(Exception("RESOURCE_EXHAUSTED: quota"))
    assert not is_rate_limited(ValueError("bad schema"))


def test_token_estimate_is_proportional():
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("") == 1


class FakeModels:
    """Stands in for client.aio.models, failing with 429 before succeeding."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        class Response:
            parsed = {
                "overview": "Fine.",
                "teaching_style": "Lectures.",
                "workload": "Light.",
                "exams": "Two.",
                "confidence": "medium",
            }
            text = "{}"

        return Response()


def make_summarizer(failures: int, sleeps: list[float]) -> GeminiSummarizer:
    """Build a GeminiSummarizer without constructing a real genai client."""
    summarizer = GeminiSummarizer.__new__(GeminiSummarizer)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = type("Client", (), {})()
    client.aio = type("Aio", (), {})()
    client.aio.models = FakeModels(failures)
    summarizer._client = client
    summarizer.model = "gemini-flash-lite-latest"
    summarizer._bucket = TokenBucket(0)
    summarizer._max_attempts = 4
    summarizer._sleep = sleep
    return summarizer


async def test_gemini_retries_after_a_rate_limit():
    sleeps: list[float] = []
    summarizer = make_summarizer(failures=2, sleeps=sleeps)
    result = await summarizer.summarize(
        SummaryRequest(kind=INSTRUCTOR, professor_name="Jane", comments=[comment("ok")])
    )

    assert summarizer._client.aio.models.calls == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0], "backoff has to grow"
    assert result.facets["overview"] == "Fine."
    assert result.model == "gemini-flash-lite-latest"


async def test_gemini_gives_up_after_max_attempts():
    sleeps: list[float] = []
    summarizer = make_summarizer(failures=99, sleeps=sleeps)
    with pytest.raises(RuntimeError):
        await summarizer.summarize(
            SummaryRequest(kind=INSTRUCTOR, professor_name="Jane", comments=[comment("ok")])
        )
    assert summarizer._client.aio.models.calls == 4


async def test_a_non_quota_error_is_not_retried():
    sleeps: list[float] = []
    summarizer = make_summarizer(failures=0, sleeps=sleeps)

    async def boom(**kwargs):
        raise ValueError("bad request")

    summarizer._client.aio.models.generate_content = boom
    with pytest.raises(ValueError):
        await summarizer.summarize(
            SummaryRequest(kind=INSTRUCTOR, professor_name="Jane", comments=[comment("ok")])
        )
    assert sleeps == []
