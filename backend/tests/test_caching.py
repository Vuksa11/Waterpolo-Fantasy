"""
Regression tests for Cache-Control/ETag on public read-only endpoints.

ETag was part of the original Phase-1 performance plan alongside
Cache-Control (docs/FRONTEND_BACKEND_HANDOFF.md) but was never actually
implemented until now -- added in app/main.py's CacheControlMiddleware.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from db.models import Competition

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def competition_id():
    from app.core.db import async_session

    async with async_session() as session:
        competition = await session.scalar(select(Competition).limit(1))
        if competition is None:
            pytest.skip("no scraped competition in dev DB -- run the scraper first")
        return competition.id


async def test_public_get_has_etag_and_supports_conditional_304(client, competition_id):
    resp1 = await client.get(f"/api/home?competition_id={competition_id}")
    assert resp1.status_code == 200
    assert resp1.headers["cache-control"] == "public, max-age=30"
    etag = resp1.headers.get("etag")
    assert etag, "public cacheable GET must carry an ETag"

    resp2 = await client.get(f"/api/home?competition_id={competition_id}", headers={"If-None-Match": etag})
    assert resp2.status_code == 304
    assert resp2.content == b""
    assert resp2.headers.get("etag") == etag

    resp3 = await client.get(f"/api/home?competition_id={competition_id}", headers={"If-None-Match": '"not-the-real-etag"'})
    assert resp3.status_code == 200
    assert resp3.content == resp1.content


async def test_private_routes_get_no_etag(client):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.headers["cache-control"] == "private, no-store"
    assert "etag" not in resp.headers
