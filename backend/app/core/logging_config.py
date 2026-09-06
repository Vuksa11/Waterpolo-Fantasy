"""
Structured logging setup -- item #6 of an independent review's (Fable)
priority list. Before this, the only visibility into a running process was
whatever landed on stdout/stderr by accident (uvicorn's own access log,
unhandled tracebacks) -- no application-level logger actually had a handler
attached, so e.g. app/core/email.py's `logger.info(...)` calls were silently
swallowed (confirmed live: registering a user produced no visible log line
at all until this was fixed).

Deliberately NOT a Sentry/Prometheus/ELK integration -- no credentials for
any of those exist for this project. This is the honest, currently-
achievable version: structured, leveled logs on stdout, which any real
log aggregator can pick up later by just pointing at the process's
output (systemd journal, docker logs, etc.) without a code change here.
"""

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level = logging.DEBUG if settings.environment == "development" else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # uvicorn configures its own loggers (uvicorn.access/uvicorn.error) with
    # their own handlers by default -- left alone here, they already work.
    # Every OTHER logger in this codebase (app.email, app.core.cache,
    # app.core.ratelimit, the scraper) has no handler of its own and
    # propagates to root, so it's covered by the single handler above.
