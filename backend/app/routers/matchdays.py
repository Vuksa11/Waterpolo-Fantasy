import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import MatchOut, TopPerformerOut
from db.models import EntityType, FantasyScore, Match, Matchday, Player

router = APIRouter(prefix="/api/matchdays", tags=["matchdays"])


@router.get("/{matchday_id}/matches", response_model=list[MatchOut])
async def list_matches(matchday_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[Match]:
    result = await db.execute(select(Match).where(Match.matchday_id == matchday_id))
    return list(result.scalars().all())


@router.get("/{matchday_id}/top-performers", response_model=list[TopPerformerOut])
async def top_performers(
    matchday_id: uuid.UUID, limit: int = Query(10, ge=1, le=100), db: AsyncSession = Depends(get_db)
) -> list[TopPerformerOut]:
    matchday = await db.get(Matchday, matchday_id)
    if matchday is None:
        raise HTTPException(status_code=404, detail="Matchday not found")

    result = await db.execute(
        select(FantasyScore, Player)
        .join(Player, Player.id == FantasyScore.entity_id)
        .where(FantasyScore.matchday_id == matchday_id, FantasyScore.entity_type == EntityType.PLAYER)
        .order_by(FantasyScore.raw_points.desc())
        .limit(limit)
    )
    return [
        TopPerformerOut(
            player_id=player.id,
            player_name=player.name,
            real_club=player.real_club,
            raw_points=float(score.raw_points),
        )
        for score, player in result.all()
    ]
