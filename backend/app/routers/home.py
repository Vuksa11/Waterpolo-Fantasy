"""
GET /api/home -- bundle endpoint agreed with the frontend session
(docs/FRONTEND_BACKEND_HANDOFF.md) to replace a 4-5 request waterfall on the
page most users land on first with a single round trip. Contract: exactly
{competition_id, selected_matchday, matches, standings_top4, updated_at} --
nothing private, nothing not shown on that page. Adding fields later is fine;
removing/renaming needs the same handoff-doc negotiation this endpoint did.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_or_compute_json
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
    # 404s (bad competition_id/matchday_id) intentionally aren't cached --
    # only the successful-response path below goes through the cache, so a
    # typo'd ID doesn't need any special-casing here.
    cache_key = f"home:v1:{competition_id}:{matchday_id or 'latest'}"
    data = await get_or_compute_json(cache_key, lambda: _compute_home(competition_id, matchday_id, db))
    return HomeOut(**data)


async def _compute_home(competition_id: uuid.UUID, matchday_id: uuid.UUID | None, db: AsyncSession) -> dict:
    # The frontend session's second review caught a real inconsistency here:
    # this used to always pick "the most recent season for this competition"
    # independently of matchday_id, then call get_standings with no season
    # filter (all seasons summed). An explicit matchday_id from an OLDER
    # season would then either 404 with a misleading "not found" message, or
    # -- once multiple seasons exist -- silently pair a matchday from one
    # season with standings summed across all of them. Fixed by deriving the
    # season FROM the matchday when one is given, and always passing that
    # exact season_id to get_standings so the two can never disagree.
    if matchday_id is not None:
        matchday = await db.get(Matchday, matchday_id)
        if matchday is None:
            raise HTTPException(status_code=404, detail="Matchday not found")
        season = await db.get(Season, matchday.season_id)
        if season is None or season.competition_id != competition_id:
            raise HTTPException(status_code=404, detail="Matchday does not belong to this competition")
    else:
        season = await db.scalar(
            select(Season).where(Season.competition_id == competition_id).order_by(Season.start_date.desc())
        )
        if season is None:
            raise HTTPException(status_code=404, detail="No season found for this competition")
        matchday = await _pick_matchday(db, season.id)

    matches: list[Match] = []
    if matchday is not None:
        result = await db.execute(select(Match).where(Match.matchday_id == matchday.id))
        matches = list(result.scalars().all())

    standings = await get_standings(competition_id, db, season_id=season.id)

    # Known limitation (frontend-session review): scrape_runs isn't scoped
    # per competition, so this is the most recent successful run across
    # EVERY tracked competition, not specifically this one -- if a future
    # competition scrapes far more often than others, this could read as
    # "just updated" for stale data. Fixing that properly needs a schema
    # change (e.g. scrape_runs gaining a competition reference); tracked as
    # a follow-up, not done here. What IS fixed: this no longer claims "just
    # updated now" when no scrape has ever run -- that's a materially worse
    # lie than "which competition" and is fixed by returning None (unknown
    # freshness) instead of the current time.
    updated_at: datetime | None = await db.scalar(
        select(ScrapeRun.finished_at)
        .where(ScrapeRun.finished_at.is_not(None))
        .order_by(ScrapeRun.finished_at.desc())
    )

    return HomeOut(
        competition_id=competition_id,
        selected_matchday=MatchdaySummary.model_validate(matchday) if matchday else None,
        matches=[MatchOut.model_validate(m) for m in matches],
        standings_top4=standings[:4],
        updated_at=updated_at,
    ).model_dump(mode="json")
