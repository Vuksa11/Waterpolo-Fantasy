"""Stateless roster validation; this endpoint does not save a fantasy team."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import LineupValidationIn, LineupValidationOut
from db.models import Player, Position

router = APIRouter(prefix="/api/lineups", tags=["lineups"])

FORMATION_COUNTS = {
    "THREE_THREE": {"GK": 1, "OT": 4, "CF": 1, "CB": 1},
    "FOUR_TWO": {"GK": 1, "OT": 4, "CF": 2, "CB": 0},
    "TWO_FOUR": {"GK": 1, "OT": 4, "CF": 0, "CB": 2},
}


@router.post("/validate", response_model=LineupValidationOut)
async def validate_lineup(
    lineup: LineupValidationIn, db: AsyncSession = Depends(get_db)
) -> LineupValidationOut:
    ids = set(lineup.active_player_ids)
    if len(ids) != 7:
        raise HTTPException(422, "A lineup must contain seven distinct players")
    if lineup.captain_id not in ids:
        raise HTTPException(422, "Captain must be an active player")
    result = await db.execute(select(Player).where(Player.id.in_(ids)))
    players = list(result.scalars().all())
    if len(players) != 7:
        raise HTTPException(422, "One or more players do not exist")
    competitions = {player.competition_id for player in players}
    if len(competitions) != 1 or (lineup.competition_id is not None and competitions != {lineup.competition_id}):
        raise HTTPException(422, "All players must belong to the selected competition")
    counts = dict.fromkeys((p.value for p in Position), 0)
    for player in players:
        if player.position not in counts:
            raise HTTPException(422, "Every player must have a verified GK, OT, CF or CB position")
        counts[player.position] += 1
    if counts != FORMATION_COUNTS[lineup.formation]:
        raise HTTPException(422, f"Formation {lineup.formation} requires {FORMATION_COUNTS[lineup.formation]}")
    return LineupValidationOut(formation=lineup.formation, counts=counts)
