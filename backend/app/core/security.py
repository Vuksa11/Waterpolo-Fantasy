"""
Password hashing and JWT access tokens.

Scoped-down v1: email+password only. The original v1 architecture doc also
specified Google OAuth and short-lived access tokens paired with refresh
tokens (see Fantasy_Waterpolo_Arhitektura_v1.pdf, Section 7.2) -- both are
deferred here since neither is needed to test the core fantasy mechanics
locally. A single longer-lived access token (7 days, see config.py) stands in
for the access+refresh pair for now.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


async def hash_password_async(password: str) -> str:
    """
    bcrypt is deliberately slow and, unlike the rest of this async codebase,
    synchronous/CPU-bound -- calling it directly from an async route blocks
    the *entire* single-threaded event loop for its full duration, stalling
    every other concurrent request being served by this process. Confirmed
    by the Phase-1 baseline load test (backend/loadtest/): POST
    /api/auth/register had a ~1.1s median under 100 concurrent simulated
    users, and *other* endpoints' p98/p99 spiked into the 1-3s range at the
    same time -- consistent with bcrypt work blocking everyone else, not
    those endpoints being slow themselves. Routes should call this (or
    verify_password_async), not the sync functions above directly.
    """
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


def create_access_token(user_id: uuid.UUID, credentials_version: int) -> str:
    """
    `credentials_version` is embedded as "cv" and checked against the
    User row's current value on every request (see deps.get_current_user) --
    this is what lets a password reset invalidate every token issued before
    it (see User.credentials_version's docstring). Callers must pass the
    version that was current AT THE TIME this token is issued (i.e. the
    just-loaded user row's value), not a stale one.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire, "cv": credentials_version}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> tuple[uuid.UUID, int] | None:
    """Returns (user_id, credentials_version) from the token, or None if it's
    malformed/expired/invalid. "cv" defaults to 0 for tokens issued before
    this field existed, matching User.credentials_version's own default."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return uuid.UUID(payload["sub"]), int(payload.get("cv", 0))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
