"""
Shared pytest fixtures for every test module in this directory.

Both the DB engine (app.core.db.engine) and the Redis client
(app.core.cache._client) are lazy, module-level singletons -- correct for
the real app (one process, one event loop, created once). pytest-asyncio
gives each test its own event loop by default, but a singleton created in
test N's loop is then reused (still referencing that now-closed loop) by
test N+1's *different* loop, raising "attached to a different loop" or
"Event loop is closed". This fixture resets both singletons after every
test so the next one creates fresh connections on whatever loop it runs on
-- it doesn't touch the app's actual (correct, single-loop) production
behavior.
"""

from urllib.parse import urlsplit, urlunsplit

import pytest_asyncio

from app.core.config import settings

# An independent review (Codex, problemV16) correctly pointed out that the
# per-test `ratelimit:*` wipe below scans and deletes keys on WHATEVER Redis
# database REDIS_URL points to -- if a developer runs pytest with the same
# .env their real dev server uses (same host, same default db 0), this
# deletes real rate-limit/lockout state for actual traffic, not just test
# leftovers. Force the whole test session onto a dedicated logical Redis DB
# (15, the conventional "scratch" index) instead, regardless of whatever db
# number (if any) the configured REDIS_URL already has -- this can never
# collide with a real deployment's traffic since nothing else in this
# project is configured to use db 15.
if settings.redis_url:
    _parts = urlsplit(settings.redis_url)
    settings.redis_url = urlunsplit((_parts.scheme, _parts.netloc, "/15", _parts.query, _parts.fragment))


@pytest_asyncio.fixture(autouse=True)
async def _reset_singleton_clients_after_test():
    # Cleared BEFORE each test, not just after: httpx's ASGITransport gives
    # every request the same fake client address (127.0.0.1), so every test
    # that hits a rate-limited endpoint (app/core/ratelimit.py) shares the
    # same Redis counter key. Without this, a test suite re-run within the
    # rate-limit window (up to an hour) would start failing real tests with
    # 429s that have nothing to do with an actual attack -- confirmed this
    # is a real risk, not theoretical, since test_frontend_api.py alone
    # calls register/login far more than the login lockout's limit of 5.
    from app.core.cache import _get_client

    client = _get_client()
    if client is not None:
        keys = [key async for key in client.scan_iter(match="ratelimit:*")]
        if keys:
            await client.delete(*keys)

    yield

    from app.core.db import engine

    await engine.dispose()

    import app.core.cache as cache_module

    # Not awaiting client.aclose() here on purpose: the client's connection
    # is bound to this test's (about to end) event loop, and closing it
    # from there is exactly the operation that raises "Event loop is
    # closed" in the first place. Dropping the reference is sufficient --
    # the next test that needs caching constructs a brand new client tied
    # to its own loop, and the old connection is garbage collected.
    cache_module._client = None
    cache_module._client_initialized = False
