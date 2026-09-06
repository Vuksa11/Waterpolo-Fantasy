import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_or_compute_json
from app.core.db import get_db
from app.schemas import PlayerCatalogOut, PlayerFacetsOut, PlayerDetailOut, PlayerOut, PlayerSeasonStats, PriceHistoryPoint
from db.models import EntityType, FantasyScore, Matchday, Player, Position, PriceHistoryEntry

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


@router.get("/catalog", response_model=PlayerCatalogOut)
async def player_catalog(
    competition_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=100),
    position: Position | None = None,
    club: str | None = Query(default=None, max_length=200),
    sort: Literal["cost_desc", "cost_asc", "current_cost_desc", "current_cost_asc", "name_asc", "name_desc"] = "cost_desc",
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PlayerCatalogOut:
    # Cached (Phase 2 of the performance plan) -- keyed on every filter/sort/
    # page combination, since each is a genuinely different result set.
    cache_key = f"catalog:v1:{competition_id}:{search}:{position}:{club}:{sort}:{limit}:{offset}"
    data = await get_or_compute_json(
        cache_key, lambda: _compute_catalog(competition_id, search, position, club, sort, limit, offset, db)
    )
    return PlayerCatalogOut(**data)


async def _compute_catalog(
    competition_id: uuid.UUID | None,
    search: str | None,
    position: Position | None,
    club: str | None,
    sort: str,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> dict:
    filters = []
    if competition_id is not None:
        filters.append(Player.competition_id == competition_id)
    if search and search.strip():
        # Treat SQL wildcard characters as literal user input.
        term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Player.name.ilike(f"%{term}%", escape="\\"))
    if position is not None:
        filters.append(Player.position == position)
    if club is not None:
        filters.append(Player.real_club == club)
    ordering = {
        "cost_desc": Player.current_cost.desc(), "cost_asc": Player.current_cost.asc(),
        "name_asc": Player.name.asc(), "name_desc": Player.name.desc(),
        "current_cost_desc": Player.current_cost.desc(), "current_cost_asc": Player.current_cost.asc(),
    }[sort]
    total = await db.scalar(select(func.count()).select_from(Player).where(*filters))
    result = await db.execute(
        select(Player).where(*filters).order_by(ordering, Player.id).limit(limit).offset(offset)
    )
    items = [PlayerOut.model_validate(p).model_dump(mode="json") for p in result.scalars().all()]
    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


@router.get("/facets", response_model=PlayerFacetsOut)
async def player_facets(
    competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> PlayerFacetsOut:
    # Cached (Phase 2 of the performance plan).
    cache_key = f"facets:v1:{competition_id}"
    data = await get_or_compute_json(cache_key, lambda: _compute_facets(competition_id, db))
    return PlayerFacetsOut(**data)


async def _compute_facets(competition_id: uuid.UUID | None, db: AsyncSession) -> dict:
    filters = [] if competition_id is None else [Player.competition_id == competition_id]
    clubs = await db.execute(select(Player.real_club).where(*filters).distinct().order_by(Player.real_club))
    # Shared contract: list supported filters even before verified positions
    # arrive. This does not assign a position to any player.
    return {"clubs": list(clubs.scalars()), "positions": [position.value for position in Position]}


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
