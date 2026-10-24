"""The hot cache: recency, expiry, single flight, negative caching, versioning."""

from __future__ import annotations

import asyncio

import pytest

from app.cache import MISSING, CacheRegistry, TTLCache, warm_professor_cache


async def yield_control(times: int = 10) -> None:
    """Let every pending task reach its next await point."""
    for _ in range(times):
        await asyncio.sleep(0)


async def test_hit_and_miss_counters(clock):
    cache = TTLCache("t", maxsize=4, ttl=10.0, clock=clock)
    assert await cache.get("a") is MISSING
    await cache.set("a", 1)
    assert await cache.get("a") == 1

    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.size) == (1, 1, 1)
    assert stats.hit_rate == 0.5


async def test_eviction_order_is_recency_not_insertion(clock):
    """The point of the cache: what survives is what was viewed most recently."""
    cache = TTLCache("t", maxsize=2, ttl=100.0, clock=clock)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.get("a")  # a is now the most recently viewed
    await cache.set("c", 3)

    assert await cache.get("b") is MISSING  # the stale one went
    assert await cache.get("a") == 1
    assert await cache.get("c") == 3
    assert cache.stats().evictions == 1


async def test_expiry_is_counted_separately_from_misses(clock):
    cache = TTLCache("t", maxsize=4, ttl=10.0, clock=clock)
    await cache.set("a", 1)
    clock.advance(9.9)
    assert await cache.get("a") == 1
    clock.advance(0.2)
    assert await cache.get("a") is MISSING

    stats = cache.stats()
    assert stats.expired == 1
    assert stats.misses == 0
    assert stats.size == 0


async def test_per_entry_ttl_overrides_the_default(clock):
    cache = TTLCache("t", maxsize=4, ttl=1000.0, clock=clock)
    await cache.set("short", 1, ttl=5.0)
    clock.advance(6)
    assert await cache.get("short") is MISSING


async def test_single_flight_collapses_concurrent_misses(clock):
    cache = TTLCache("t", maxsize=4, ttl=100.0, clock=clock)
    calls = 0
    first_call_started = asyncio.Event()
    release = asyncio.Event()

    async def factory():
        nonlocal calls
        calls += 1
        first_call_started.set()
        await release.wait()
        return "value"

    tasks = [asyncio.create_task(cache.get_or_compute("k", factory)) for _ in range(20)]
    await first_call_started.wait()
    await yield_control()
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1, "twenty requests for one cold professor must do one query"
    assert results == ["value"] * 20
    assert cache.stats().single_flight_joins == 19


async def test_single_flight_propagates_failure_and_caches_nothing(clock):
    cache = TTLCache("t", maxsize=4, ttl=100.0, clock=clock)
    attempts = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def factory():
        nonlocal attempts
        attempts += 1
        started.set()
        await release.wait()
        raise RuntimeError("database down")

    tasks = [asyncio.create_task(cache.get_or_compute("k", factory)) for _ in range(3)]
    await started.wait()
    await yield_control()
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert attempts == 1
    assert all(isinstance(r, RuntimeError) for r in results)
    assert await cache.get("k") is MISSING  # a failure must not be remembered


async def test_a_second_attempt_after_failure_runs_again(clock):
    cache = TTLCache("t", maxsize=4, ttl=100.0, clock=clock)
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return "ok"

    with pytest.raises(RuntimeError):
        await cache.get_or_compute("k", factory)
    assert await cache.get_or_compute("k", factory) == "ok"
    assert calls == 2


async def test_negative_caching_remembers_a_missing_professor(clock):
    cache = TTLCache("t", maxsize=4, ttl=100.0, negative_ttl=10.0, clock=clock)
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return None

    assert await cache.get_or_compute("prof:999", factory) is None
    assert await cache.get_or_compute("prof:999", factory) is None
    assert calls == 1, "a hammered bad id must not re-query Postgres"

    stats = cache.stats()
    assert stats.negative_hits == 1

    clock.advance(11)
    assert await cache.get_or_compute("prof:999", factory) is None
    assert calls == 2, "negative entries expire sooner than real ones"


async def test_without_a_negative_ttl_none_is_not_cached(clock):
    cache = TTLCache("t", maxsize=4, ttl=100.0, negative_ttl=0.0, clock=clock)
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return None

    await cache.get_or_compute("k", factory)
    await cache.get_or_compute("k", factory)
    assert calls == 2


async def test_cache_state_reports_hit_miss_and_join(clock):
    from app.cache import CACHE_STATE

    cache = TTLCache("t", maxsize=4, ttl=100.0, clock=clock)

    async def factory():
        return 1

    await cache.get_or_compute("k", factory)
    assert CACHE_STATE.get() == "MISS"
    await cache.get_or_compute("k", factory)
    assert CACHE_STATE.get() == "HIT"


async def test_invalidate_prefix_and_clear(clock):
    cache = TTLCache("t", maxsize=10, ttl=100.0, clock=clock)
    for key in ("v1:prof:1", "v1:prof:2", "v1:search:x"):
        await cache.set(key, key)

    assert await cache.invalidate_prefix("v1:prof:") == 2
    assert await cache.get("v1:search:x") == "v1:search:x"
    assert await cache.clear() == 1


async def test_data_version_namespaces_keys_and_bumping_clears(settings, clock):
    registry = CacheRegistry(settings, data_version=4, clock=clock)
    assert registry.key("prof", 7) == "v4:prof:7"

    await registry.professors.set(registry.key("prof", 7), {"name": "old"})
    changed = await registry.set_data_version(5)

    assert changed is True
    assert registry.key("prof", 7) == "v5:prof:7"
    assert registry.professors.stats().size == 0, "an ingest run must not leave stale rows"
    assert await registry.set_data_version(5) is False


async def test_version_check_is_rate_limited(settings, clock):
    registry = CacheRegistry(settings, clock=clock)
    registry.version_check_interval = 30.0

    assert registry.due_for_version_check() is False  # just constructed
    clock.advance(31)
    assert registry.due_for_version_check() is True
    assert registry.due_for_version_check() is False


async def test_search_filters_hash_into_one_key(settings, clock):
    registry = CacheRegistry(settings, clock=clock)
    same = registry.digest({"q": "doe", "dept": None, "limit": 20})
    reordered = registry.digest({"limit": 20, "dept": None, "q": "doe"})
    different = registry.digest({"q": "doe", "dept": "MATH", "limit": 20})

    assert same == reordered
    assert same != different


async def test_recently_viewed_dedupes_and_keeps_newest_first(settings, clock):
    registry = CacheRegistry(settings, clock=clock)
    for instructor_id, name in ((1, "A"), (2, "B"), (1, "A"), (3, "C"), (4, "D")):
        await registry.recents.record(instructor_id, name)

    snapshot = await registry.recents.snapshot()
    assert [view.instructor_id for view in snapshot] == [4, 3, 1]  # maxsize 3


async def test_stats_payload_shape(settings, clock):
    registry = CacheRegistry(settings, data_version=2, clock=clock)
    await registry.professors.set(registry.key("prof", 1), {"full_name": "A"})
    await registry.recents.record(1, "A")

    payload = await registry.stats_payload()
    assert payload["data_version"] == 2
    assert {c["name"] for c in payload["caches"]} == {"professors", "search"}
    assert payload["recently_viewed"][0]["instructor_id"] == 1


async def test_warm_professor_cache_preloads_and_skips_unknown(settings, clock):
    registry = CacheRegistry(settings, clock=clock)

    async def loader(instructor_id: int):
        return {"full_name": f"prof {instructor_id}"} if instructor_id != 2 else None

    warmed = await warm_professor_cache(registry, loader, [1, 2, 3])

    assert warmed == 2
    assert await registry.professors.get(registry.key("prof", 1)) == {"full_name": "prof 1"}
    assert await registry.professors.get(registry.key("prof", 2)) is MISSING
