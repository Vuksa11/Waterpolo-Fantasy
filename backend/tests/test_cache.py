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
