from __future__ import annotations

import pytest

from app.config import Settings


class FakeClock:
    """A hand-advanced monotonic clock, so TTL tests never sleep."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    """Small caches, so eviction is reachable in a test."""
    return Settings(
        database_url="postgresql+asyncpg://unused/unused",
        cache_professor_size=3,
        cache_professor_ttl=100.0,
        cache_search_size=2,
        cache_search_ttl=50.0,
        cache_negative_ttl=10.0,
        recents_size=3,
    )
