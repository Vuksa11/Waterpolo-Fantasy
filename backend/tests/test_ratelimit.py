"""
Regression tests for app/core/ratelimit.py, using fakeredis (real Redis wire
protocol, in-memory) the same way test_cache.py does.
"""

import asyncio

import fakeredis
import pytest
from fastapi import HTTPException

import app.core.cache as cache_module
from app.core.ratelimit import (
    _increment_with_ttl,
    check_lockout,
    clear_lockout,
    enforce_rate_limit,
    get_client_ip,
    record_failed_attempt,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache_module._client = client
    cache_module._client_initialized = True
    yield client
    cache_module._client = None
    cache_module._client_initialized = False


async def test_first_increment_gets_ttl_atomically(fake_redis_client):
    """An independent review (Codex) caught that the previous version did
    `INCR` then a SEPARATE `EXPIRE` only when the result was 1 -- if the
    process died (or that EXPIRE call itself failed) between the two, the
    key was left with no expiry at all. Reproduced directly with fakeredis
    before fixing: TTL stayed -1 (never expires) forever. SET NX EX must set
    both atomically so this can't happen for a newly created key."""
    count = await _increment_with_ttl(fake_redis_client, "rl:new-key", window_seconds=60)
    ttl = await fake_redis_client.ttl("rl:new-key")
    assert count == 1
    assert ttl > 0, "a freshly created counter must never have TTL -1 (no expiry)"


async def test_damaged_key_self_heals(fake_redis_client):
    """Simulates a key from before this fix (or a crash right after
    creation) that's missing its TTL -- the next increment must notice and
    fix it, not leave it permanently stuck over its limit."""
    await fake_redis_client.set("rl:damaged", 3)  # no TTL, as if EXPIRE never ran
    assert await fake_redis_client.ttl("rl:damaged") == -1

    count = await _increment_with_ttl(fake_redis_client, "rl:damaged", window_seconds=60)
    ttl = await fake_redis_client.ttl("rl:damaged")
    assert count == 4
    assert ttl > 0, "a key missing its TTL must be healed, not left permanently stuck"


async def test_enforce_rate_limit_blocks_over_limit_and_resets():
    key = "ratelimit:test:blocks"
    for _ in range(3):
        await enforce_rate_limit(key, limit=3, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(key, limit=3, window_seconds=60)
    assert exc_info.value.status_code == 429


async def test_login_lockout_blocks_after_limit_and_clears_on_success():
    key = "ratelimit:test:lockout"
    await check_lockout(key, limit=5, window_seconds=900)  # not locked out yet

    for _ in range(5):
        await record_failed_attempt(key, window_seconds=900)

    with pytest.raises(HTTPException) as exc_info:
        await check_lockout(key, limit=5, window_seconds=900)
    assert exc_info.value.status_code == 429

    await clear_lockout(key)
    await check_lockout(key, limit=5, window_seconds=900)  # must not raise anymore


async def test_check_lockout_self_heals_legacy_counter_without_ttl(fake_redis_client):
    """An independent review (Codex, problemV16) found that a counter
    already at/over the limit but missing its TTL (from before the
    SET-NX-EX fix, or otherwise damaged) stays locked out forever: since
    check_lockout is read-only and runs BEFORE record_failed_attempt's own
    self-heal ever gets a chance to, that healing path was unreachable for
    an already-locked-out key. check_lockout must heal it itself."""
    key = "ratelimit:test:legacy-lockout"
    await fake_redis_client.set(key, 5)  # as if created before SET NX EX existed -- no TTL
    assert await fake_redis_client.ttl(key) == -1

    with pytest.raises(HTTPException) as exc_info:
        await check_lockout(key, limit=5, window_seconds=900)
    assert exc_info.value.status_code == 429

    ttl = await fake_redis_client.ttl(key)
    assert ttl > 0, "check_lockout must heal a damaged counter's missing TTL, not just report it as locked out forever"


def _fake_request(client_host: str | None, headers: dict | None = None):
    from unittest.mock import MagicMock

    request = MagicMock()
    request.client = MagicMock(host=client_host) if client_host is not None else None
    request.headers = headers or {}
    return request


async def test_get_client_ip_ignores_forwarded_header_from_untrusted_source():
    """A direct connection NOT from a known local proxy must never have its
    X-Forwarded-For trusted -- otherwise an arbitrary client could forge
    that header to reset its own rate limit."""
    request = _fake_request("203.0.113.5", headers={"x-forwarded-for": "1.2.3.4"})
    assert get_client_ip(request) == "203.0.113.5"


async def test_get_client_ip_trusts_forwarded_header_from_local_proxy():
    """Confirmed live (Codex, problemV15): the frontend dev server doesn't
    set this header today, so this path isn't exercised by it yet -- but
    must work correctly once it does, without another backend change."""
    request = _fake_request("127.0.0.1", headers={"x-forwarded-for": "203.0.113.9, 127.0.0.1"})
    assert get_client_ip(request) == "203.0.113.9"


async def test_get_client_ip_falls_back_to_direct_address_without_header():
    request = _fake_request("127.0.0.1", headers={})
    assert get_client_ip(request) == "127.0.0.1"


async def test_rate_limit_fails_open_without_redis(monkeypatch):
    """Consistent with the cache module's philosophy: Redis being absent
    must never block a legitimate request."""
    cache_module._client = None
    cache_module._client_initialized = True  # pretend init already happened, found nothing configured
    try:
        await enforce_rate_limit("ratelimit:test:no-redis", limit=0, window_seconds=60)  # would 429 if enforced
    finally:
        cache_module._client_initialized = False
