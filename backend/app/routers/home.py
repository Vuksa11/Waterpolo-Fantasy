"""
GET /api/home -- bundle endpoint agreed with the frontend session
(docs/FRONTEND_BACKEND_HANDOFF.md) to replace a 4-5 request waterfall on the
page most users land on first with a single round trip. Contract: exactly
{competition_id, selected_matchday, matches, standings_top4, updated_at} --
nothing private, nothing not shown on that page. Adding fields later is fine;
removing/renaming needs the same handoff-doc negotiation this endpoint did.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.routers.competitions import get_standings
from app.schemas import HomeOut, MatchdaySummary, MatchOut
from db.models import Match, Matchday, MatchdayStatus, ScrapeRun, Season

router = APIRouter(prefix="/api/home", tags=["home"])


async def _pick_matchday(db: AsyncSession, season_id: uuid.UUID) -> Matchday | None:
    """Same "current matchday" heuristic as teams.py's transfer tagging: the
    first UPCOMING one, or the last one overall if the season is fully
    finished (true of every season scraped so far)."""
    matchday = await db.scalar(
        select(Matchday)
        .where(Matchday.season_id == season_id, Matchday.status == MatchdayStatus.UPCOMING)
        .order_by(Matchday.number.asc())
    )
    if matchday is None:
        matchday = await db.scalar(
            select(Matchday).where(Matchday.season_id == season_id).order_by(Matchday.number.desc())
        )
    return matchday


@router.get("", response_model=HomeOut)
async def home(
    competition_id: uuid.UUID,
    matchday_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> HomeOut:
    season = await db.scalar(
        select(Season).where(Season.competition_id == competition_id).order_by(Season.start_date.desc())
    )
    if season is None:
        raise HTTPException(status_code=404, detail="No season found for this competition")

    if matchday_id is not None:
        matchday = await db.get(Matchday, matchday_id)
        if matchday is None or matchday.season_id != season.id:
            raise HTTPException(status_code=404, detail="Matchday not found for this competition")
    else:
        matchday = await _pick_matchday(db, season.id)

    matches: list[Match] = []
    if matchday is not None:
        result = await db.execute(select(Match).where(Match.matchday_id == matchday.id))
        matches = list(result.scalars().all())

    standings = await get_standings(competition_id, db)

    last_run_finished_at = await db.scalar(
        select(ScrapeRun.finished_at).where(ScrapeRun.finished_at.is_not(None)).order_by(ScrapeRun.finished_at.desc())
    )

    return HomeOut(
        competition_id=competition_id,
        selected_matchday=MatchdaySummary.model_validate(matchday) if matchday else None,
        matches=[MatchOut.model_validate(m) for m in matches],
        standings_top4=standings[:4],
        updated_at=last_run_finished_at or datetime.now(timezone.utc),
    )
