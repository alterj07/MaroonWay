"""The server-side hot cache.

Professor detail pages are the most-hit and most-expensive read in MaroonWay: a
handful of joins plus a stored LLM summary, for the same few professors a student
opens over and over. This module keeps those in process memory.

Three things make it more than a dict:

* **Recency is the eviction order.** Every hit moves its key to the end of an
  ``OrderedDict``, so what gets evicted is always the least recently *viewed*
  professor. "Cache of the most recently viewed professors" is not a separate
  feature here -- it is what LRU eviction means.
* **Single flight.** If twenty requests ask for the same cold professor at once,
  one computes and nineteen await that result, instead of twenty identical
  round trips to Postgres.
* **Negative caching.** A missing id is remembered briefly, so a crawler
  hammering /professors/999999 cannot re-query the database on every request.

Scope, deliberately: this cache is process-local. Run uvicorn with one worker --
two workers means two independent caches and roughly half the hit rate (still
correct, just slower). Swapping in Redis later means reimplementing ``TTLCache``
behind the same methods; nothing in the routers would change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.config import Settings

# Set by get_or_compute, read by the X-Cache middleware in main.py.
CACHE_STATE: ContextVar[str | None] = ContextVar("cache_state", default=None)

# Distinguishes "no entry" from an entry whose value is None (a negative cache
# hit, i.e. we know this professor does not exist).
MISSING: Any = object()

Clock = Callable[[], float]


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float
    negative: bool = False


@dataclass(slots=True)
class CacheStats:
    name: str
    size: int
    maxsize: int
    ttl: float
    hits: int = 0
    misses: int = 0
    negative_hits: int = 0
    expired: int = 0
    evictions: int = 0
    single_flight_joins: int = 0
    stores: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses + self.expired

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl,
            "hits": self.hits,
            "misses": self.misses,
            "negative_hits": self.negative_hits,
            "expired": self.expired,
            "evictions": self.evictions,
            "single_flight_joins": self.single_flight_joins,
            "stores": self.stores,
            "hit_rate": round(self.hit_rate, 4),
        }


def _swallow(future: asyncio.Future) -> None:
    """Retrieve an in-flight future's exception so Python stops warning about it.

    Every joiner awaits the future and re-raises for itself; this only silences
    the "exception was never retrieved" message in the case where nobody joined.
    """
    if not future.cancelled():
        future.exception()


class TTLCache:
    """An async LRU cache with per-entry TTL, single flight, and counters."""

    def __init__(
        self,
        name: str,
        maxsize: int,
        ttl: float,
        *,
        negative_ttl: float = 0.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.name = name
        self.maxsize = max(1, maxsize)
        self.ttl = ttl
        self.negative_ttl = negative_ttl
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._negative_hits = 0
        self._expired = 0
        self._evictions = 0
        self._joins = 0
        self._stores = 0

    # -- reads -------------------------------------------------------------

    async def get(self, key: str) -> Any:
        """Return the cached value, or ``MISSING``.

        A negatively cached key returns ``None``, which is a hit: we know the
        answer and the answer is "no such thing".
        """
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return MISSING
            if entry.expires_at <= self._clock():
                del self._entries[key]
                self._expired += 1
                return MISSING
            self._entries.move_to_end(key)  # recency == eviction order
            self._hits += 1
            if entry.negative:
                self._negative_hits += 1
            return entry.value

    async def get_or_compute(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        ttl: float | None = None,
    ) -> Any:
        """Serve ``key`` from cache, else run ``factory`` exactly once.

        A factory returning ``None`` is cached negatively when a negative TTL is
        configured. Sets ``CACHE_STATE`` to HIT, MISS (this call computed), or
        JOIN (this call waited on another's computation).
        """
        cached = await self.get(key)
        if cached is not MISSING:
            CACHE_STATE.set("HIT")
            return cached

        async with self._lock:
            inflight = self._inflight.get(key)
            owner = inflight is None
            if owner:
                inflight = asyncio.get_running_loop().create_future()
                inflight.add_done_callback(_swallow)
                self._inflight[key] = inflight
            else:
                self._joins += 1

        assert inflight is not None
        if not owner:
            CACHE_STATE.set("JOIN")
            return await inflight

        try:
            value = await factory()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            await self._finish(key, inflight, exc=exc)
            raise

        negative = value is None
        if not negative or self.negative_ttl > 0:
            await self.set(key, value, ttl=ttl, negative=negative)
        await self._finish(key, inflight, value=value)
        CACHE_STATE.set("MISS")
        return value

    async def _finish(
        self,
        key: str,
        inflight: asyncio.Future,
        *,
        value: Any = None,
        exc: BaseException | None = None,
    ) -> None:
        async with self._lock:
            if self._inflight.get(key) is inflight:
                del self._inflight[key]
        if inflight.done():
            return
        if exc is not None:
            inflight.set_exception(exc)
        else:
            inflight.set_result(value)

    # -- writes ------------------------------------------------------------

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: float | None = None,
        negative: bool = False,
    ) -> None:
        async with self._lock:
            if ttl is not None:
                effective = ttl
            elif negative:
                effective = self.negative_ttl
            else:
                effective = self.ttl
            self._entries[key] = _Entry(value, self._clock() + effective, negative)
            self._entries.move_to_end(key)
            self._stores += 1
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)
                self._evictions += 1

    async def invalidate(self, key: str) -> bool:
        async with self._lock:
            return self._entries.pop(key, None) is not None

    async def invalidate_prefix(self, prefix: str) -> int:
        async with self._lock:
            doomed = [k for k in self._entries if k.startswith(prefix)]
            for key in doomed:
                del self._entries[key]
            return len(doomed)

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    # -- introspection -----------------------------------------------------

    def stats(self) -> CacheStats:
        return CacheStats(
            name=self.name,
            size=len(self._entries),
            maxsize=self.maxsize,
            ttl=self.ttl,
            hits=self._hits,
            misses=self._misses,
            negative_hits=self._negative_hits,
            expired=self._expired,
            evictions=self._evictions,
            single_flight_joins=self._joins,
            stores=self._stores,
        )

    def keys(self) -> list[str]:
        """Keys, least recently used first. For tests and /cache/stats."""
        return list(self._entries)


@dataclass(frozen=True, slots=True)
class RecentView:
    instructor_id: int
    name: str
    at: float

    def as_dict(self) -> dict[str, Any]:
        return {"instructor_id": self.instructor_id, "name": self.name, "at": self.at}


class RecentlyViewed:
    """A short log of which professors were just opened.

    Pure observability -- the professor cache is what actually makes repeat views
    fast. This exists so /cache/stats can show what is hot right now.
    """

    def __init__(self, maxsize: int, *, clock: Clock = time.time) -> None:
        self._items: deque[RecentView] = deque(maxlen=max(1, maxsize))
        self._clock = clock
        self._lock = asyncio.Lock()

    async def record(self, instructor_id: int, name: str) -> None:
        async with self._lock:
            for existing in list(self._items):
                if existing.instructor_id == instructor_id:
                    self._items.remove(existing)
                    break
            self._items.appendleft(RecentView(instructor_id, name, self._clock()))

    async def snapshot(self) -> list[RecentView]:
        async with self._lock:
            return list(self._items)


class CacheRegistry:
    """The caches, their shared key namespace, and the recents log.

    Two of them, not three: stored summaries ride along inside the professor
    payload, so they are already behind the professor cache and a separate
    summaries cache would only duplicate it.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        data_version: int = 0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.professors = TTLCache(
            "professors",
            settings.cache_professor_size,
            settings.cache_professor_ttl,
            negative_ttl=settings.cache_negative_ttl,
            clock=clock,
        )
        self.search = TTLCache(
            "search",
            settings.cache_search_size,
            settings.cache_search_ttl,
            clock=clock,
        )
        self.recents = RecentlyViewed(settings.recents_size)
        self.data_version = data_version
        self._clock = clock
        self.version_check_interval = 30.0
        self._version_checked_at = clock()

    def caches(self) -> dict[str, TTLCache]:
        return {c.name: c for c in (self.professors, self.search)}

    # -- keys --------------------------------------------------------------

    def key(self, *parts: Any) -> str:
        """Namespace a key with the current data version.

        Every ingest job bumps ``data_version``, which makes every existing key
        unreachable in one step -- no sweep, no stale blend of old and new rows.
        """
        tail = ":".join("*" if p is None else str(p) for p in parts)
        return f"v{self.data_version}:{tail}"

    @staticmethod
    def digest(payload: Mapping[str, Any]) -> str:
        """A short stable hash of filter values, for search keys."""
        canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    async def set_data_version(self, version: int) -> bool:
        """Adopt a new data version, dropping everything cached under the old one."""
        if version == self.data_version:
            return False
        self.data_version = version
        await self.invalidate_all()
        return True

    def due_for_version_check(self) -> bool:
        """Whether it is time to re-read data_version from Postgres.

        One cheap query every ``version_check_interval`` seconds, so an ingest
        job that bumps the version gets picked up without restarting the API and
        without a per-request round trip that would defeat the cache.
        """
        now = self._clock()
        if now - self._version_checked_at < self.version_check_interval:
            return False
        self._version_checked_at = now
        return True

    async def invalidate_all(self) -> dict[str, int]:
        return {name: await cache.clear() for name, cache in self.caches().items()}

    async def stats_payload(self) -> dict[str, Any]:
        return {
            "data_version": self.data_version,
            "caches": [cache.stats().as_dict() for cache in self.caches().values()],
            "recently_viewed": [view.as_dict() for view in await self.recents.snapshot()],
        }


def get_caches(request: Request) -> CacheRegistry:
    """FastAPI dependency. The registry lives on app.state, not a module global,
    so each test can build a fresh one."""
    return request.app.state.caches


async def warm_professor_cache(
    registry: CacheRegistry,
    loader: Callable[[int], Awaitable[Any]],
    instructor_ids: Iterable[int],
) -> int:
    """Pre-load professor payloads at boot so the first click is a HIT."""
    warmed = 0
    for instructor_id in instructor_ids:
        payload = await loader(instructor_id)
        if payload is None:
            continue
        await registry.professors.set(registry.key("prof", instructor_id), payload)
        warmed += 1
    return warmed
