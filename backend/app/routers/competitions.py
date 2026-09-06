import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import CompetitionOut, MatchdayOut, StandingsRow
from db.models import Competition, Match, Matchday, MatchStatus, Season

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


@router.get("", response_model=list[CompetitionOut])
async def list_competitions(db: AsyncSession = Depends(get_db)) -> list[Competition]:
    result = await db.execute(select(Competition))
    return list(result.scalars().all())


@router.get("/{competition_id}/standings", response_model=list[StandingsRow])
async def get_standings(
    competition_id: uuid.UUID, db: AsyncSession = Depends(get_db), season_id: uuid.UUID | None = None
) -> list[StandingsRow]:
    """
    Computed from finished matches -- there's no standings table (the
    platform doesn't need one; this is just for viewing the scraped data).
    Simplification: every finished match is scored as a plain win/loss (3/0
    points). Water polo rarely ends level (ties go to a penalty shootout,
    tracked separately as `psoscore` on the source site) but a genuine tie
    score isn't specially handled here -- see module TODO if one shows up.

    `season_id` is optional and defaults to every season for this
    competition (today that's the same thing -- only one season exists per
    competition). It exists so a caller that already picked a specific
    season (see home.py, which caught a real bug here: it was picking a
    matchday from one season while this endpoint silently summed matches
    across all of them) can keep the two consistent.
    """
    query = (
        select(Match)
        .join(Matchday, Matchday.id == Match.matchday_id)
        .join(Season, Season.id == Matchday.season_id)
        .where(Season.competition_id == competition_id, Match.status == MatchStatus.FINISHED)
    )
    if season_id is not None:
        query = query.where(Season.id == season_id)
    result = await db.execute(query)
    matches = result.scalars().all()
    if not matches:
        return []

    table: dict[str, StandingsRow] = {}

    def row(club: str) -> StandingsRow:
        if club not in table:
            table[club] = StandingsRow(
                club=club, played=0, won=0, lost=0, goals_for=0, goals_against=0, goal_difference=0, points=0
            )
        return table[club]

    for m in matches:
        home_score, away_score = m.home_score or 0, m.away_score or 0
        home, away = row(m.home_club), row(m.away_club)
        home.played += 1
        away.played += 1
        home.goals_for += home_score
        home.goals_against += away_score
        away.goals_for += away_score
        away.goals_against += home_score
        if home_score > away_score:
            home.won += 1
            home.points += 3
            away.lost += 1
        elif away_score > home_score:
            away.won += 1
            away.points += 3
            home.lost += 1

    for r in table.values():
        r.goal_difference = r.goals_for - r.goals_against

    return sorted(table.values(), key=lambda r: (-r.points, -r.goal_difference, -r.goals_for))


@router.get("/{competition_id}/matchdays", response_model=list[MatchdayOut])
async def list_matchdays(competition_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[Matchday]:
    result = await db.execute(
        select(Matchday)
        .join(Season, Season.id == Matchday.season_id)
        .where(Season.competition_id == competition_id)
        .order_by(Matchday.number)
    )
    matchdays = result.scalars().all()
    return [MatchdayOut.model_validate(md) for md in matchdays]
