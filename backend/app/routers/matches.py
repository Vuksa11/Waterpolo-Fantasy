import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import MatchDetailOut, PlayerStatOut
from db.models import Match, Player, PlayerStat
from scoring.engine import player_raw_points

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/{match_id}", response_model=MatchDetailOut)
async def get_match(match_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> MatchDetailOut:
    match = await db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    result = await db.execute(
        select(PlayerStat, Player).join(Player, Player.id == PlayerStat.player_id).where(
            PlayerStat.match_id == match_id
        )
    )
    rows = result.all()

    player_stats = [
        PlayerStatOut(
            player_id=player.id,
            player_name=player.name,
            club=player.real_club,
            goals=stat.goals,
            assists=stat.assists,
            fouls_drawn=stat.fouls_drawn,
            steals=stat.steals,
            blocks=stat.blocks,
            swimoffs_won=stat.swimoffs_won,
            misses=stat.misses,
            personal_fouls=stat.personal_fouls,
            turnovers=stat.turnovers,
            offensive_fouls=stat.offensive_fouls,
            saves=stat.saves,
            goals_conceded=stat.goals_conceded,
            raw_points=player_raw_points(stat),
        )
        for stat, player in rows
    ]
    player_stats.sort(key=lambda p: -p.raw_points)

    return MatchDetailOut(
        id=match.id,
        external_id=match.external_id,
        home_club=match.home_club,
        away_club=match.away_club,
        home_score=match.home_score,
        away_score=match.away_score,
        status=match.status,
        kickoff_at=match.kickoff_at,
        player_stats=player_stats,
    )
