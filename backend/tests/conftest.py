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

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_singleton_clients_after_test():
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
