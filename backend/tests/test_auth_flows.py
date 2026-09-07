"""
Regression tests for email verification, password reset, and the rate
limiting/lockout added to app/routers/auth.py -- all built in response to
an independent review (Fable) that confirmed live (15 consecutive wrong
passwords, all clean 401s, no lockout) that none of this existed before.

Runs against the real dev Postgres DB. Rate-limit/lockout tests need a real
Redis (app/core/ratelimit.py fails open -- i.e. does nothing -- without one,
which is correct production behavior but means those specific assertions
can't be verified without it) and skip themselves if REDIS_URL isn't
configured; the email-verification/password-reset tests don't depend on
Redis at all and always run.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from db.models import User

pytestmark = pytest.mark.asyncio

requires_redis = pytest.mark.skipif(not settings.redis_url, reason="rate limiting is a no-op without REDIS_URL set")


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import async_session

    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client, db_session):
    email = f"authflow-{uuid.uuid4()}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "originalpass123", "display_name": "Auth Flow Test"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    yield {"email": email, "token": token}

    await db_session.execute(User.__table__.delete().where(User.email == email))
    await db_session.commit()


async def test_register_sets_unverified_email(client, registered_user):
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {registered_user['token']}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_verified"] is False


async def test_verify_email_flow(client, db_session, registered_user):
    user = await db_session.scalar(select(User).where(User.email == registered_user["email"]))
    assert user.email_verification_token is not None

    resp = await client.get(f"/api/auth/verify-email?token={user.email_verification_token}")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {registered_user['token']}"})
    assert resp.json()["email_verified"] is True

    # Token consumed -- reusing it must not silently succeed again.
    stale_token = user.email_verification_token
    await db_session.refresh(user)
    assert user.email_verification_token is None
    resp = await client.get(f"/api/auth/verify-email?token={stale_token}")
    assert resp.status_code == 422


async def test_verify_email_rejects_unknown_token(client):
    resp = await client.get("/api/auth/verify-email?token=this-token-does-not-exist")
    assert resp.status_code == 422


async def test_forgot_password_gives_same_response_for_unknown_email(client, registered_user):
    known = await client.post("/api/auth/forgot-password", json={"email": registered_user["email"]})
    unknown = await client.post("/api/auth/forgot-password", json={"email": "definitely-not-registered@example.com"})
    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == unknown.json(), "must not reveal whether an email is registered (enumeration risk)"


async def test_password_reset_flow(client, db_session, registered_user):
    await client.post("/api/auth/forgot-password", json={"email": registered_user["email"]})
    user = await db_session.scalar(select(User).where(User.email == registered_user["email"]))
    assert user.password_reset_token is not None

    resp = await client.post(
        "/api/auth/reset-password", json={"token": user.password_reset_token, "new_password": "brandnewpass456"}
    )
    assert resp.status_code == 200, resp.text

    old_login = await client.post(
        "/api/auth/login", json={"email": registered_user["email"], "password": "originalpass123"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/auth/login", json={"email": registered_user["email"], "password": "brandnewpass456"}
    )
    assert new_login.status_code == 200


async def test_reset_password_rejects_unknown_token(client):
    resp = await client.post("/api/auth/reset-password", json={"token": "not-a-real-token", "new_password": "x" * 10})
    assert resp.status_code == 422


async def test_reset_password_invalidates_previously_issued_tokens(client, db_session, registered_user):
    """An independent review (Codex, problemV16) found that resetting a
    password didn't invalidate tokens already issued -- a token obtained
    before the reset (e.g. by an attacker who had the old password) kept
    working normally until its own 7-day expiry, defeating the point of a
    reset in response to a suspected compromise."""
    old_token = registered_user["token"]

    await client.post("/api/auth/forgot-password", json={"email": registered_user["email"]})
    user = await db_session.scalar(select(User).where(User.email == registered_user["email"]))
    resp = await client.post(
        "/api/auth/reset-password", json={"token": user.password_reset_token, "new_password": "brandnewpass456"}
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert resp.status_code == 401, "a token issued before the password reset must stop working immediately"

    new_login = await client.post(
        "/api/auth/login", json={"email": registered_user["email"], "password": "brandnewpass456"}
    )
    assert new_login.status_code == 200
    new_token = new_login.json()["access_token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert resp.status_code == 200, "a token issued AFTER the reset must work normally"


async def test_reset_password_race_only_one_concurrent_request_succeeds(client, db_session, registered_user):
    """An independent review (Codex, problemV16) found and reproduced (in
    isolation) that reset_password had no protection against two concurrent
    requests racing on the same still-valid token -- both could read it as
    valid and both successfully set a (different) new password, with no
    error to either caller. This test exercises the real endpoint, through
    the real ASGI app, against the real dev Postgres DB, with two genuinely
    concurrent requests -- not an isolated reproduction of just the query."""
    await client.post("/api/auth/forgot-password", json={"email": registered_user["email"]})
    user = await db_session.scalar(select(User).where(User.email == registered_user["email"]))
    token = user.password_reset_token
    assert token is not None

    responses = await asyncio.gather(
        client.post("/api/auth/reset-password", json={"token": token, "new_password": "racepassword1"}),
        client.post("/api/auth/reset-password", json={"token": token, "new_password": "racepassword2"}),
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 422], (
        f"exactly one concurrent request with the same token should succeed and the other rejected "
        f"as an already-used token, got {[r.status_code for r in responses]}"
    )

    # Whichever password won, exactly one of the two logs in -- never both,
    # never neither.
    login_attempts = await asyncio.gather(
        client.post("/api/auth/login", json={"email": registered_user["email"], "password": "racepassword1"}),
        client.post("/api/auth/login", json={"email": registered_user["email"], "password": "racepassword2"}),
    )
    login_statuses = sorted(r.status_code for r in login_attempts)
    assert login_statuses == [200, 401]


@requires_redis
async def test_login_lockout_after_repeated_failures(client, registered_user):
    email = registered_user["email"]
    for _ in range(5):
        resp = await client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        assert resp.status_code == 401

    resp = await client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
    assert resp.status_code == 429

    # Even the CORRECT password is locked out until the window passes --
    # that's the point of a lockout, not a bug.
    resp = await client.post("/api/auth/login", json={"email": email, "password": "originalpass123"})
    assert resp.status_code == 429


@requires_redis
async def test_login_lockout_clears_on_success(client, registered_user):
    email = registered_user["email"]
    for _ in range(2):
        resp = await client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        assert resp.status_code == 401

    resp = await client.post("/api/auth/login", json={"email": email, "password": "originalpass123"})
    assert resp.status_code == 200

    # A legitimate user who mistyped a couple of times then succeeded must
    # not be penalized on their next attempts.
    for _ in range(3):
        resp = await client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        assert resp.status_code == 401, "lockout counter should have been cleared by the successful login"
