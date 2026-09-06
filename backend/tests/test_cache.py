"""
Regression tests for app/core/cache.py -- the Phase 2 Redis cache layer.

Real Redis isn't installed on this dev machine yet (sudo isn't available in
this environment to install it), so these use fakeredis (in-memory, real
Redis wire protocol semantics including TTL) to prove the cache actually
works -- hits, misses, and TTL expiry -- not just that it degrades
gracefully when Redis is absent (that's covered by every other test in this
suite already passing with no REDIS_URL set at all, plus a manual check
against a real REDIS_URL pointing at nothing, confirmed to log a warning
and return 200 rather than fail).
"""

import asyncio

import fakeredis
import pytest

import app.core.cache as cache_module

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_redis_client():
    """Swap the module's lazy singleton for a fake one so _get_client()
    never tries to actually dial the network, and reset it after so other
    tests (which expect no cache configured) aren't affected."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache_module._client = client
    cache_module._client_initialized = True
    yield client
    cache_module._client = None
    cache_module._client_initialized = False


async def test_cache_hit_skips_recompute(fake_redis_client):
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = await cache_module.get_or_compute_json("test:key", compute, ttl=30)
    second = await cache_module.get_or_compute_json("test:key", compute, ttl=30)

    assert first == {"value": 1}
    assert second == {"value": 1}, "second call should replay the cached value, not recompute"
    assert calls == 1, "compute() must only run once -- the second call was a cache hit"


async def test_different_keys_dont_collide(fake_redis_client):
    async def compute_a():
        return {"who": "a"}

    async def compute_b():
        return {"who": "b"}

    a = await cache_module.get_or_compute_json("test:a", compute_a, ttl=30)
    b = await cache_module.get_or_compute_json("test:b", compute_b, ttl=30)

    assert a == {"who": "a"}
    assert b == {"who": "b"}


async def test_ttl_expiry_forces_recompute(fake_redis_client):
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"value": calls}

    await cache_module.get_or_compute_json("test:ttl", compute, ttl=1)
    assert calls == 1

    await asyncio.sleep(1.2)

    result = await cache_module.get_or_compute_json("test:ttl", compute, ttl=1)
    assert result == {"value": 2}, "after TTL expiry, a fresh value must be computed and cached again"
    assert calls == 2


async def test_redis_failure_falls_back_to_compute(fake_redis_client, monkeypatch):
    """Same failure-injection technique used elsewhere in this suite:
    simulate Redis erroring mid-request (not just being absent) and confirm
    get_or_compute_json still returns a correct result instead of raising."""

    async def broken_get(*args, **kwargs):
        raise ConnectionError("simulated Redis outage")

    monkeypatch.setattr(fake_redis_client, "get", broken_get)

    async def compute():
        return {"ok": True}

    result = await cache_module.get_or_compute_json("test:broken", compute, ttl=30)
    assert result == {"ok": True}


async def test_make_cache_key_does_not_collide_on_separator_characters():
    """An independent review (Codex) caught that the old naive
    f"{search}:{club}" key format let two DIFFERENT filter combinations
    collide when a value contained the ":" separator itself: confirmed
    search="a:None:b",club="c" produced the exact same key as
    search="a",club="b:None:c". make_cache_key must not have this problem."""
    key_a = cache_module.make_cache_key("catalog", search="a:None:b", position=None, club="c")
    key_b = cache_module.make_cache_key("catalog", search="a", position=None, club="b:None:c")
    assert key_a != key_b, "different filters must never produce the same cache key"

    # Same params (any order) -> same key, so it's still actually usable as a cache.
    key_c = cache_module.make_cache_key("catalog", club="c", position=None, search="a:None:b")
    assert key_a == key_c


async def test_get_client_falls_back_on_invalid_redis_url(monkeypatch):
    """An independent review (Codex) caught that _get_client() constructed
    the Redis client OUTSIDE any try/except, so a malformed REDIS_URL raised
    ValueError synchronously and propagated straight out of
    get_or_compute_json -- the opposite of every other failure mode in this
    module, which degrades to a cache miss instead of crashing the request."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "redis_url", "invalid://not-a-real-scheme")
    cache_module._client = None
    cache_module._client_initialized = False
    try:
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            return {"ok": True}

        result = await cache_module.get_or_compute_json("test:invalid-url", compute)
        assert result == {"ok": True}
        assert calls == 1, "must fall through to compute(), not raise"
    finally:
        cache_module._client = None
        cache_module._client_initialized = False


async def test_concurrent_cache_misses_compute_once(fake_redis_client):
    """An independent review (Codex) found 25 concurrent callers with a cold
    cache all ran compute() themselves (25 DB round-trips instead of 1) --
    get_or_compute_json must deduplicate concurrent misses for the same key
    within this process."""
    calls = 0

    async def slow_compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"value": "computed-once"}

    results = await asyncio.gather(*[cache_module.get_or_compute_json("test:stampede", slow_compute) for _ in range(25)])

    assert calls == 1, f"compute() should run exactly once for 25 concurrent misses, ran {calls} times"
    assert all(r == {"value": "computed-once"} for r in results)
