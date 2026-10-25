"""Request pacing, shared by the scraper and the LLM jobs.

Both upstreams need to be treated gently for different reasons: Gemini's free
tier counts requests per minute, and RateMyProfessors is being scraped rather
than consumed through an API.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any


class TokenBucket:
    """A requests-per-minute throttle shared by every concurrent task."""

    def __init__(
        self,
        rate_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.interval = 60.0 / rate_per_minute if rate_per_minute > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Wait until the next request is allowed; returns how long it waited."""
        if self.interval <= 0:
            return 0.0
        async with self._lock:
            now = self._clock()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if wait:
            await self._sleep(wait)
        return wait
