"""
Email delivery -- currently a stub, not wired to a real provider.

No SMTP/SendGrid/SES credentials exist for this project, so there is no way
to actually deliver an email right now. Rather than silently pretending to
send one (which would leave a user who registers or requests a password
reset with no way to ever receive their link), this logs the would-be
email's content clearly at INFO level so it's visible in the server console
during development.

Before a real deployment: replace the body of `send_email` with a real
provider call (and remove the log-based fallback, or keep it as a
dev-only branch behind `settings.environment == "development"`). Nothing
else in the codebase needs to change -- every caller already goes through
this one function.
"""

import logging

logger = logging.getLogger("app.email")


async def send_email(to: str, subject: str, body: str) -> None:
    logger.info("EMAIL (not actually sent -- no provider configured) to=%s subject=%r\n%s", to, subject, body)
