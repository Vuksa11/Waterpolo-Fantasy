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

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_client_initialized = False

# Deduplicates concurrent cache misses for the SAME key within this process
# (see get_or_compute_json): every concurrent caller for a key currently
# being computed awaits the SAME in-flight task instead of starting its own,
# and the entry is removed the moment that computation finishes -- so this
# dict only ever holds keys that are ACTIVELY being computed right now, not
# every key ever seen (an independent review, Codex problemV16, correctly
# pointed out the previous per-key-Lock version never removed entries,
# growing without bound across the real key space -- confirmed with 200
# unique keys leaving 201 dead locks behind). Doesn't help across multiple
# worker processes; each has its own dict, so a multi-worker deployment
# still sees per-process stampedes.
_inflight: dict[str, "asyncio.Task[Any]"] = {}


def make_cache_key(prefix: str, **params: Any) -> str:
    """
    Builds a collision-safe cache key from named parameters. NOT naive string
    interpolation with a separator like `f"{a}:{b}"` -- an independent review
    (Codex) caught that a parameter value containing the separator itself
    lets two DIFFERENT parameter combinations collide: with
    `f"catalog:{search}:{club}"`, search="a:None:b",club="c" produces the
    exact same string as search="a",club="b:None:c". Confirmed independently
    before fixing.

    JSON-encoding (sorted keys, so argument order never matters) and hashing
    that instead makes every distinct combination of parameters produce a
    distinct key regardless of what characters they contain.
    """
    canonical = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _get_client():
    """Lazy singleton -- constructing a redis client doesn't itself connect,
    so this is cheap to call on every request; the real failure mode (Redis
    unreachable) is handled at GET/SET time below. Constructing the client
    itself can ALSO fail synchronously (e.g. a malformed REDIS_URL raises
    ValueError immediately, confirmed independently) -- caught here so that
    failure degrades to "no cache" like every other failure mode in this
    module, instead of propagating out of every caller."""
    global _client, _client_initialized
    if not _client_initialized:
        if settings.redis_url:
            try:
                import redis.asyncio as redis

                _client = redis.Redis.from_url(
                    settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
                )
            except Exception:
                logger.warning(
                    "Failed to construct a Redis client from REDIS_URL -- caching/rate limiting disabled",
                    exc_info=True,
                )
                _client = None
        # Only marked initialized AFTER the attempt (whether it succeeded or
        # not), not before -- a construction failure means "stay disabled
        # for this process's lifetime" (a malformed URL won't fix itself),
        # not "retry every call".
        _client_initialized = True
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
    themselves).

    Concurrent misses for the SAME key are deduplicated within this process:
    the first caller starts a single `compute()` task and every other
    concurrent caller for that key awaits that SAME task instead of running
    their own. This matters even without Redis configured at all -- a
    per-key `asyncio.Lock` version of this (the original fix for an
    independent review's 25-concurrent-callers-run-compute-25-times finding)
    only serialized those calls without sharing the result, so with caching
    disabled it still ran `compute()` once per waiter, just one at a time
    instead of in parallel (a second independent review, Codex problemV16,
    caught this and reproduced it: 25 calls, `compute()` ran 25 times).
    Sharing the actual in-flight task fixes both that and the previous
    version's unbounded key growth (see `_inflight`'s comment) in one move.
    """
    cached = await cache_get_json(key)
    if cached is not None:
        return cached

    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_compute_and_cache(key, compute, ttl))
        _inflight[key] = task
    return await task


async def _compute_and_cache(key: str, compute: Callable[[], Awaitable[Any]], ttl: int | None) -> Any:
    try:
        value = await compute()
        await cache_set_json(key, value, ttl)
        return value
    finally:
        # Always remove, success or failure -- a failed compute must not
        # leave the key permanently "in flight" with nobody left to clean it
        # up, and a successful one has nothing left to dedupe once it's done.
        _inflight.pop(key, None)
