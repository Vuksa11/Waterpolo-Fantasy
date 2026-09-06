import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import PlayerDetailOut, PlayerOut, PlayerSeasonStats, PriceHistoryPoint
from db.models import EntityType, FantasyScore, Matchday, Player, PriceHistoryEntry

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("", response_model=list[PlayerOut])
async def list_players(
    competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[Player]:
    query = select(Player)
    if competition_id is not None:
        query = query.where(Player.competition_id == competition_id)
    result = await db.execute(query.order_by(Player.current_cost.desc()))
    return list(result.scalars().all())


@router.get("/{player_id}", response_model=PlayerDetailOut)
async def get_player(player_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PlayerDetailOut:
    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    scores_result = await db.execute(
        select(FantasyScore).where(
            FantasyScore.entity_type == EntityType.PLAYER, FantasyScore.entity_id == player_id
        )
    )
    scores = scores_result.scalars().all()
    total_raw = float(sum(s.raw_points for s in scores))

    history_result = await db.execute(
        select(PriceHistoryEntry, Matchday)
        .join(Matchday, Matchday.id == PriceHistoryEntry.matchday_id)
        .where(PriceHistoryEntry.entity_type == EntityType.PLAYER, PriceHistoryEntry.entity_id == player_id)
        .order_by(Matchday.number)
    )
    price_history = [
        PriceHistoryPoint(
            matchday_number=md.number,
            matchday_label=md.label,
            old_cost=float(ph.old_cost),
            new_cost=float(ph.new_cost),
        )
        for ph, md in history_result.all()
    ]

    return PlayerDetailOut(
        **PlayerOut.model_validate(player).model_dump(),
        season=PlayerSeasonStats(total_raw_points=total_raw, matchdays_played=len(scores)),
        price_history=price_history,
    )
