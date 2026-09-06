from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://waterpolo:waterpolo@localhost:5432/waterpolo_fantasy"

    # Dev-only default -- MUST be overridden via .env (JWT_SECRET=...) before
    # any real deployment. Anyone with this value can forge valid tokens.
    jwt_secret: str = "dev-insecure-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days -- no refresh-token flow yet (see docs, Section 7)


settings = Settings()
