"""
Redis-backed rate limiting for auth endpoints. Motivated by an independent
review (Fable, separate session) that confirmed live: 15 consecutive wrong
passwords against the same account all returned a clean 401, no lockout, no
429 -- bcrypt's own cost (~240ms/attempt) is friction, not protection.

Two distinct mechanisms, both needed:
- `enforce_rate_limit`: a blanket per-key throttle (increment-then-check,
  fixed window) for "don't let one source hammer this endpoint" -- used per
  client IP on both register and login.
- `check_lockout`/`record_failed_attempt`/`clear_lockout`: a
  check-before/increment-after-failure pair specifically for login, keyed
  by email, so an account gets locked out after N *failed* attempts
  regardless of source IP (closing the exact gap Fable demonstrated) while
  a legitimate user who mistypes once then succeeds is never penalized.

Shares the same lazy Redis singleton as app/core/cache.py (one connection,
not two) rather than duplicating the lazy-init logic.

Fails OPEN, not closed: if Redis is absent or errors, every check here logs
a warning and allows the request through. This is a deliberate tradeoff
consistent with the cache module's philosophy (a Redis outage must never
take the API down with it) -- the alternative, failing closed, would mean a
Redis blip locks every user out of login/register entirely. Documented
limitation, not an oversight: this makes rate limiting itself unenforced
during a Redis outage, same as caching becomes a no-op then.
"""

import logging

from fastapi import HTTPException, Request, status

from app.core.cache import _get_client

logger = logging.getLogger(__name__)

# Only the frontend dev server (frontend/server.mjs) proxies to this API
# today, always from the same machine. A real deployment behind an actual
# reverse proxy/load balancer needs this to list THAT proxy's real address
# instead.
_TRUSTED_PROXY_IPS = {"127.0.0.1", "::1"}


def get_client_ip(request: Request) -> str:
    """
    Identifies the real client for rate-limiting purposes.

    Only trusts an `X-Forwarded-For` header if the DIRECT TCP connection
    came from a known local proxy -- an arbitrary client could otherwise
    send its own `X-Forwarded-For` to reset its own rate limit, which is
    exactly why this isn't read unconditionally.

    Confirmed live (independent review, Codex, problemV15): the frontend
    dev server currently does NOT set this header at all when it proxies
    `/api/*`, so every browser user going through it shares one rate-limit
    bucket today (all requests arrive from 127.0.0.1). This function is
    ready for the moment that changes (a one-line addition to
    frontend/server.mjs setting `X-Forwarded-For` to the real client
    address) without needing another backend change -- not implemented
    here since it's their file, proposed in the handoff doc instead.
    """
    direct_ip = request.client.host if request.client else "unknown"
    if direct_ip in _TRUSTED_PROXY_IPS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The convention is client, proxy1, proxy2, ... -- the first
            # entry is the original client as far as the trusted proxy saw.
            return forwarded.split(",")[0].strip()
    return direct_ip


async def _increment_with_ttl(client, key: str, window_seconds: int) -> int:
    """
    Atomically creates the counter WITH its expiry in one Redis command
    (`SET key 1 NX EX window_seconds`) on the first call, or increments the
    existing counter (no separate EXPIRE call needed -- the TTL was already
    set at creation) on subsequent calls.

    Fixes a real race an independent review (Codex) found and I reproduced
    directly: the previous version did `INCR` then a SEPARATE `EXPIRE` only
    when the result was 1. If the process died (or that EXPIRE call itself
    failed) between the two, the key was left with NO expiry at all --
    confirmed with fakeredis: TTL stayed -1 (never expires) forever after,
    permanently stuck over its limit with no way to reset. `SET NX EX` sets
    both atomically, so that gap can't happen for a newly created key.

    Also self-heals a key that's ALREADY missing its TTL (from before this
    fix, or the narrow window right after a `SET NX EX` where a concurrent
    caller's INCR lands before this one's own TTL check) by setting one
    on the next call that observes it -- worst case that races harmlessly
    with another caller doing the same (EXPIRE is idempotent), and if THAT
    call is itself interrupted, the next one heals it instead.
    """
    created = await client.set(key, 1, nx=True, ex=window_seconds)
    if created:
        return 1
    count = await client.incr(key)
    ttl = await client.ttl(key)
    if ttl == -1:
        await client.expire(key, window_seconds)
    return count


async def enforce_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    """Increments `key`'s counter (atomically creating it with its expiry on
    first use) and raises 429 if it now exceeds `limit` within
    `window_seconds`."""
    client = _get_client()
    if client is None:
        return
    try:
        count = await _increment_with_ttl(client, key, window_seconds)
        ttl = await client.ttl(key) if count > limit else None
    except Exception:
        logger.warning("Rate limit check failed for key %r -- failing open", key, exc_info=True)
        return
    if count > limit:
        headers = {"Retry-After": str(ttl)} if ttl and ttl > 0 else None
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Try again later.", headers=headers)


async def check_lockout(key: str, limit: int) -> None:
    """Read-only check -- does NOT increment. Raises 429 if `key` already
    has `limit` or more recorded failures. Call before doing any expensive
    work (like bcrypt verification) so a locked-out account fails fast."""
    client = _get_client()
    if client is None:
        return
    try:
        raw = await client.get(key)
        ttl = await client.ttl(key) if raw is not None else None
    except Exception:
        logger.warning("Lockout check failed for key %r -- failing open", key, exc_info=True)
        return
    if raw is not None and int(raw) >= limit:
        headers = {"Retry-After": str(ttl)} if ttl and ttl > 0 else None
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed login attempts. Try again later.", headers=headers
        )


async def record_failed_attempt(key: str, window_seconds: int) -> None:
    """Call only after a failed password verification -- increments the
    failure counter, atomically starting a fresh window on the first
    failure (see _increment_with_ttl's docstring for why not a separate
    INCR + EXPIRE)."""
    client = _get_client()
    if client is None:
        return
    try:
        await _increment_with_ttl(client, key, window_seconds)
    except Exception:
        logger.warning("Recording failed login attempt failed for key %r", key, exc_info=True)


async def clear_lockout(key: str) -> None:
    """Call after a SUCCESSFUL login so a user who mistyped their password
    a few times before getting it right isn't penalized later."""
    client = _get_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        logger.warning("Clearing lockout failed for key %r", key, exc_info=True)
