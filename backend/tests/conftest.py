from __future__ import annotations

import pytest

from app.config import Settings, get_settings


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


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch):
    """Keep every test off the network.

    backend/.env legitimately holds real keys for local runs, and
    pydantic-settings reads it -- so without this a test that builds a decider
    or a summariser would quietly call Gemini or Jev for real. Environment
    variables win over the .env file, so emptying them here is enough.
    """
    for name in ("TYPESAFE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
