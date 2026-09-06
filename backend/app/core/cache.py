"""
Phase 2 of the performance plan (docs/FRONTEND_BACKEND_HANDOFF.md) -- an
optional Redis cache in front of the read-mostly endpoints that also carry
Cache-Control (standings/catalog/facets/home). Motivated by a real
measurement, not a guess: a 1000-concurrent read-only load test saturated a
single process's DB connection pool and produced real request timeouts
(sqlalchemy.exc.TimeoutError), and adding worker processes only partially
closed the gap. Cutting how many requests ever reach Postgres for data that
only changes after a scraper run closes the rest of it.

Every function here degrades to "no cache" on any failure -- a Redis outage
must never take the API down with it, only make it as slow as it was before
this existed. `settings.redis_url` being unset (the default) means the same
thing: this module is inert, every call is a guaranteed cache miss.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_client_initialized = False


def _get_client():
    """Lazy singleton -- constructing a redis client doesn't itself connect,
    so this is cheap to call on every request; the real failure mode (Redis
    unreachable) is handled at GET/SET time below, not here."""
    global _client, _client_initialized
    if not _client_initialized:
        _client_initialized = True
        if settings.redis_url:
            import redis.asyncio as redis

            _client = redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
            )
    return _client


async def cache_get_json(key: str) -> Any | None:
    client = _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:
        logger.warning("Redis GET failed for key %r -- falling back to the DB", key, exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def cache_set_json(key: str, value: Any, ttl: int | None = None) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value), ex=ttl if ttl is not None else settings.redis_cache_ttl_seconds)
    except Exception:
        logger.warning("Redis SET failed for key %r -- continuing without caching this response", key, exc_info=True)


async def get_or_compute_json(
    key: str, compute: Callable[[], Awaitable[Any]], ttl: int | None = None
) -> Any:
    """The one function routes actually call: try the cache, fall through to
    `compute()` (the real DB query) on a miss OR any cache failure, then
    best-effort populate the cache for next time. `compute()`'s return value
    must be JSON-serializable (plain dicts/lists/primitives -- build these
    from Pydantic models with `.model_dump(mode="json")`, not the models
    themselves)."""
    cached = await cache_get_json(key)
    if cached is not None:
        return cached
    value = await compute()
    await cache_set_json(key, value, ttl)
    return value
