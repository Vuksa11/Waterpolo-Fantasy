"""
Email delivery -- currently a stub, not wired to a real provider.

No SMTP/SendGrid/SES credentials exist for this project, so there is no way
to actually deliver an email right now. Rather than silently pretending to
send one (which would leave a user who registers or requests a password
reset with no way to ever receive their link), this logs the would-be
email's content -- but ONLY in development (`settings.environment ==
"development"`); outside it, only a token-free notice is logged, since the
body carries a live auth token (see send_email's own docstring).

Before a real deployment: replace the body of `send_email` with a real
provider call. Nothing else in the codebase needs to change -- every caller
already goes through this one function.
"""

import logging

from app.core.config import settings

logger = logging.getLogger("app.email")


async def send_email(to: str, subject: str, body: str) -> None:
    """
    `body` carries live email-verification/password-reset tokens (see
    auth.py's register/forgot_password) -- an independent review (Codex,
    problemV16) correctly pointed out that logging it unconditionally means
    anyone with read access to server logs outside development effectively
    has those tokens, which is exactly the "no real delivery" problem this
    stub exists to be honest about, not a reason to leak them elsewhere.
    Logging the full body (dev-only, for visibility) is fine because a
    local dev server's console isn't a shared/persisted log sink the way a
    real deployment's is.
    """
    if settings.environment == "development":
        logger.info("EMAIL (not actually sent -- no provider configured) to=%s subject=%r\n%s", to, subject, body)
    else:
        logger.warning(
            "EMAIL NOT SENT (no provider configured) to=%s subject=%r -- body withheld from logs outside "
            "development to avoid leaking verification/reset tokens",
            to,
            subject,
        )
