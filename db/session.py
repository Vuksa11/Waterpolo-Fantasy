"""Sync SQLAlchemy session factory, shared by the scraper (a one-shot cron
script — no need for async there) and Alembic. The FastAPI backend uses its
own async engine/session in backend/app/core/db.py against the same schema."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
