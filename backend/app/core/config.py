from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://waterpolo:waterpolo@localhost:5432/waterpolo_fantasy"

    # SQLAlchemy's async engine defaults to pool_size=5, max_overflow=10 --
    # 15 connections total, a hard bottleneck for the ~1000-concurrent-user
    # target (see docs/FRONTEND_BACKEND_HANDOFF.md, performance plan). These
    # are per-process; with N gunicorn/uvicorn workers behind a real
    # deployment, actual Postgres connections = db_pool_size * N, which is
    # why a pooler (PgBouncer) sits in front of Postgres once there's more
    # than one worker process -- Postgres itself has a hard max_connections
    # ceiling (~100-300 typical) that raw per-process pools would blow past.
    db_pool_size: int = 20
    db_max_overflow: int = 20

    # Default freshness window for Cache-Control on read-mostly endpoints
    # (standings/catalog/facets/matchdays) -- these only change when the
    # scraper writes new data, not per-request, so a short cache window costs
    # nothing in correctness but saves a real DB round-trip on repeat views.
    cache_control_max_age_seconds: int = 30

    # Phase 2 of the performance plan. None (default) means "no server-side
    # cache" -- reads always hit Postgres, same as before this existed.
    # Deliberately NOT required: a 1000-concurrent-read load test (see
    # docs/FRONTEND_BACKEND_HANDOFF.md) confirmed a single process's DB pool
    # saturates and times out at that load even with multiple workers
    # helping some, so this closes the remaining gap -- but Redis being
    # down must never take the API down with it (see app/core/cache.py).
    redis_url: str | None = None
    # Same freshness window as Cache-Control by default -- these are the
    # same "only changes after a scraper run" endpoints, no reason for two
    # different staleness windows to reason about.
    redis_cache_ttl_seconds: int = 30

    # Dev-only default -- MUST be overridden via .env (JWT_SECRET=...) before
    # any real deployment. Anyone with this value can forge valid tokens.
    jwt_secret: str = "dev-insecure-secret-change-in-production"
    environment: str = "development"

    @model_validator(mode="after")
    def production_secret(self):
        if self.environment != "development" and (self.jwt_secret == "dev-insecure-secret-change-in-production" or len(self.jwt_secret) < 32):
            raise ValueError("Set JWT_SECRET to a private random value of at least 32 characters outside development")
        return self

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days -- no refresh-token flow yet (see docs, Section 7)

    # Used to build email-verification/password-reset links. Matches the
    # frontend dev server's actual port (see CONTINUE.md) -- override via
    # .env for any other deployment.
    frontend_base_url: str = "http://localhost:3000"
    email_verification_token_ttl_hours: int = 48
    password_reset_token_ttl_hours: int = 1


settings = Settings()
