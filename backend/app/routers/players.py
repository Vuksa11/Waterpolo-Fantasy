import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import (
    PlayerCatalogOut,
    PlayerDetailOut,
    PlayerFacetsOut,
    PlayerOut,
    PlayerSeasonStats,
    PriceHistoryPoint,
)
from db.models import EntityType, FantasyScore, Matchday, Player, Position, PriceHistoryEntry

router = APIRouter(prefix="/api/players", tags=["players"])

_CATALOG_SORT_MAP = {
    "current_cost_desc": Player.current_cost.desc(),
    "current_cost_asc": Player.current_cost.asc(),
    "name_asc": Player.name.asc(),
    "name_desc": Player.name.desc(),
}


@router.get("", response_model=list[PlayerOut])
async def list_players(
    competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[Player]:
    query = select(Player)
    if competition_id is not None:
        query = query.where(Player.competition_id == competition_id)
    result = await db.execute(query.order_by(Player.current_cost.desc()))
    return list(result.scalars().all())


@router.get("/catalog", response_model=PlayerCatalogOut)
async def player_catalog(
    competition_id: uuid.UUID | None = None,
    search: str | None = None,
    position: str | None = None,
    club: str | None = None,
    sort: str = "current_cost_desc",
    limit: int = 24,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> PlayerCatalogOut:
    """
    Paginated, filterable, DB-side player list -- the contract agreed with the
    frontend session in docs/FRONTEND_BACKEND_HANDOFF.md. `limit` is clamped
    to [1, 100]. Sort always tie-breaks on `id` so pagination is stable even
    when many players share the same cost/name.
    """
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    if position is not None and position not in Position.__members__:
        raise HTTPException(status_code=422, detail=f"Invalid position '{position}'")

    conditions = []
    if competition_id is not None:
        conditions.append(Player.competition_id == competition_id)
    if search:
        conditions.append(Player.name.ilike(f"%{search}%"))
    if position is not None:
        conditions.append(Player.position == Position(position))
    if club is not None:
        conditions.append(Player.real_club == club)

    count_query = select(func.count()).select_from(Player)
    query = select(Player)
    for cond in conditions:
        count_query = count_query.where(cond)
        query = query.where(cond)

    order = _CATALOG_SORT_MAP.get(sort, _CATALOG_SORT_MAP["current_cost_desc"])
    query = query.order_by(order, Player.id.asc()).limit(limit).offset(offset)

    total = await db.scalar(count_query)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return PlayerCatalogOut(
        items=[PlayerOut.model_validate(p) for p in items], total=total or 0, limit=limit, offset=offset
    )


@router.get("/facets", response_model=PlayerFacetsOut)
async def player_facets(
    competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> PlayerFacetsOut:
    """Positions are always the full fixed enum (GK/OT/CF/CB), not just
    whatever's populated -- every position is currently null in the data (see
    docs, Section 7), so deriving facets from actual rows would return none."""
    query = select(Player.real_club).distinct()
    if competition_id is not None:
        query = query.where(Player.competition_id == competition_id)
    result = await db.execute(query.order_by(Player.real_club))
    clubs = [c for (c,) in result.all()]

    return PlayerFacetsOut(clubs=clubs, positions=[p.value for p in Position])


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
