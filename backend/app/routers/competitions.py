import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_or_compute_json, make_cache_key
from app.core.db import get_db
from app.schemas import CompetitionOut, LeaderboardOut, MatchdayOut, StandingsRow
from db.models import Competition, FantasyTeam, League, Match, Matchday, MatchStatus, Season, User

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

    Cached (Phase 2 of the performance plan) -- only changes when the
    scraper writes new match results, same freshness window as the
    Cache-Control header this route already carries.
    """
    cache_key = make_cache_key("standings:v2", competition_id=competition_id, season_id=season_id)
    data = await get_or_compute_json(cache_key, lambda: _compute_standings(competition_id, db, season_id))
    return [StandingsRow(**row) for row in data]


async def _compute_standings(competition_id: uuid.UUID, db: AsyncSession, season_id: uuid.UUID | None) -> list[dict]:
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

    ranked = sorted(table.values(), key=lambda r: (-r.points, -r.goal_difference, -r.goals_for))
    return [r.model_dump(mode="json") for r in ranked]


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


@router.get("/{competition_id}/leaderboard", response_model=LeaderboardOut)
async def get_leaderboard(
    competition_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardOut:
    """
    Ranks fantasy teams in the one global public league for this
    competition's latest season by `total_points`, highest first (ties
    broken by team creation order, oldest first, for stable pagination).

    Known gap, not fixed here (see docs/Fantasy_Waterpolo_Arhitektura_v2.md,
    Section 7, item 8): nothing currently aggregates a matchday's
    fantasy_scores into a team's total_points based on its saved lineup --
    that's deferred until players.position exists and lineup management is
    unblocked. Until then every team's total_points stays at its default
    (0), so this endpoint is correct in shape but shows an all-zero
    leaderboard on real data today. Built now anyway since it's independent
    of that blocker and the ranking/pagination logic won't need to change
    once scoring is wired up -- only the numbers will.

    Cached (Phase 2 of the performance plan), same pattern as standings.
    """
    cache_key = make_cache_key("leaderboard:v2", competition_id=competition_id, limit=limit, offset=offset)
    data = await get_or_compute_json(cache_key, lambda: _compute_leaderboard(competition_id, limit, offset, db))
    return LeaderboardOut(**data)


async def _compute_leaderboard(competition_id: uuid.UUID, limit: int, offset: int, db: AsyncSession) -> dict:
    season = await db.scalar(
        select(Season)
        .where(Season.competition_id == competition_id)
        .order_by(Season.start_date.desc(), Season.id)
        .limit(1)
    )
    if season is None:
        raise HTTPException(status_code=404, detail="No season found for this competition")

    league = await db.scalar(select(League).where(League.season_id == season.id, League.admin_id.is_(None)))
    if league is None:
        # Nobody has created a team in this competition yet -- the global
        # league is provisioned lazily by POST /api/teams, never by a read.
        return {
            "competition_id": str(competition_id),
            "league_id": None,
            "total": 0,
            "limit": limit,
            "offset": offset,
            "entries": [],
        }

    total = await db.scalar(select(func.count()).select_from(FantasyTeam).where(FantasyTeam.league_id == league.id))
    result = await db.execute(
        select(FantasyTeam, User.display_name)
        .join(User, User.id == FantasyTeam.user_id)
        .where(FantasyTeam.league_id == league.id)
        .order_by(FantasyTeam.total_points.desc(), FantasyTeam.created_at.asc(), FantasyTeam.id.asc())
        .limit(limit)
        .offset(offset)
    )
    entries = [
        {
            "rank": offset + i + 1,
            "team_id": str(team.id),
            "team_name": team.name,
            "owner_display_name": display_name,
            "total_points": float(team.total_points),
        }
        for i, (team, display_name) in enumerate(result.all())
    ]
    return {
        "competition_id": str(competition_id),
        "league_id": str(league.id),
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "entries": entries,
    }
