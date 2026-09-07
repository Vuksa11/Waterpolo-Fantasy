import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.email import send_email
from app.core.ratelimit import check_lockout, clear_lockout, enforce_rate_limit, get_client_ip, record_failed_attempt
from app.core.security import create_access_token, hash_password_async, verify_password_async
from app.deps import get_current_user
from app.schemas import (
    MessageOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    TokenOut,
    UserLoginIn,
    UserOut,
    UserRegisterIn,
)
from db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegisterIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    # Registration should be infrequent for a legitimate user -- a blanket
    # per-IP throttle here mainly stops mass account creation, not a
    # targeted attack on one account (there's nothing to lock out yet).
    await enforce_rate_limit(f"ratelimit:register:ip:{get_client_ip(request)}", limit=5, window_seconds=3600)

    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=body.email,
        password_hash=await hash_password_async(body.password),
        display_name=body.display_name,
        email_verification_token=secrets.token_urlsafe(32),
        email_verification_token_expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.email_verification_token_ttl_hours),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)

    # See app/core/email.py: no real provider is wired up yet, so this logs
    # the link rather than delivering it. Login is NOT gated on verifying
    # it (see the User model's email_verified comment) for that same reason.
    verify_link = f"{settings.frontend_base_url}/verify-email?token={user.email_verification_token}"
    await send_email(user.email, "Potvrdite svoj nalog", f"Kliknite da potvrdite email: {verify_link}")

    return TokenOut(access_token=create_access_token(user.id, user.credentials_version))


@router.post("/login", response_model=TokenOut)
async def login(body: UserLoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    # Found live by an independent review (Fable): 15 consecutive wrong
    # passwords against the same account all returned a clean 401 with no
    # lockout -- bcrypt's cost slows an attacker, it doesn't stop one.
    #
    # Two layers: a generous per-IP throttle (stops one source hammering
    # this endpoint across many accounts) and a stricter per-EMAIL lockout
    # counting only failures (stops a targeted attack on one account
    # regardless of source IP). The lockout check runs before touching the
    # DB or bcrypt at all, so a locked-out account fails fast.
    client_ip = get_client_ip(request)
    await enforce_rate_limit(f"ratelimit:login:ip:{client_ip}", limit=30, window_seconds=3600)
    lockout_key = f"ratelimit:login:email:{body.email}"
    await check_lockout(lockout_key, limit=5, window_seconds=900)

    user = await db.scalar(select(User).where(User.email == body.email))
    if (
        user is None
        or user.password_hash is None
        or not await verify_password_async(body.password, user.password_hash)
    ):
        await record_failed_attempt(lockout_key, window_seconds=900)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await clear_lockout(lockout_key)
    return TokenOut(access_token=create_access_token(user.id, user.credentials_version))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/verify-email", response_model=MessageOut)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> MessageOut:
    """
    A GET that changes state -- a deliberate, common exception to that rule
    for email-verification links specifically, since the link must be
    directly clickable from an email client. A frontend page at this same
    path can instead load first and issue its own POST if a stricter
    pattern is wanted later; no client depends on this shape yet.
    """
    user = await db.scalar(select(User).where(User.email_verification_token == token))
    if user is None:
        raise HTTPException(422, "Invalid or already-used verification token")
    if user.email_verification_token_expires_at is None or user.email_verification_token_expires_at < datetime.now(
        timezone.utc
    ):
        raise HTTPException(422, "Verification token has expired")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    await db.commit()
    return MessageOut(detail="Email verified")


@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(
    body: PasswordResetRequestIn, request: Request, db: AsyncSession = Depends(get_db)
) -> MessageOut:
    await enforce_rate_limit(f"ratelimit:forgot-password:ip:{get_client_ip(request)}", limit=5, window_seconds=3600)

    # Always the same response whether or not the email exists -- confirming
    # or denying that from this endpoint is a real account-enumeration risk.
    generic_response = MessageOut(detail="Ako je taj email registrovan, poslat je link za reset lozinke.")
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None:
        return generic_response

    user.password_reset_token = secrets.token_urlsafe(32)
    user.password_reset_token_expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.password_reset_token_ttl_hours
    )
    await db.commit()

    reset_link = f"{settings.frontend_base_url}/reset-password?token={user.password_reset_token}"
    await send_email(user.email, "Reset lozinke", f"Kliknite da resetujete lozinku: {reset_link}")
    return generic_response


@router.post("/reset-password", response_model=MessageOut)
async def reset_password(body: PasswordResetConfirmIn, db: AsyncSession = Depends(get_db)) -> MessageOut:
    """
    `with_for_update()` closes a real race an independent review (Codex,
    problemV16) found and reproduced: without a lock, two concurrent
    requests carrying the same (still-valid) token can both read the token
    as valid before either commits, then both successfully set a new
    password -- whichever commits last silently wins, with no error to the
    loser.

    The lock is acquired here and held for the rest of this request
    (including the slow bcrypt hash below, same tradeoff already made for
    `create_team`'s Season lock -- see its comment). A concurrent request
    for the SAME token blocks on this row until the first commits; Postgres
    then re-checks this SELECT's WHERE clause against the now-committed row
    before granting the lock, and since the token column is already NULL by
    then, the second request correctly finds no matching row instead of
    proceeding.
    """
    user = await db.scalar(select(User).where(User.password_reset_token == body.token).with_for_update())
    if user is None:
        raise HTTPException(422, "Invalid or already-used reset token")
    if user.password_reset_token_expires_at is None or user.password_reset_token_expires_at < datetime.now(
        timezone.utc
    ):
        raise HTTPException(422, "Reset token has expired")

    # Consumed on the same row-locked user object as the hash below, so both
    # land in the one UPDATE this transaction commits -- there is no
    # window where the token is cleared but the new password isn't set, or
    # vice versa.
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    user.password_hash = await hash_password_async(body.new_password)
    # Invalidates every token issued before this reset -- see
    # User.credentials_version's docstring.
    user.credentials_version += 1
    await db.commit()
    return MessageOut(detail="Lozinka je uspešno promenjena")
