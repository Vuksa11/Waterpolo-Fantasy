"""
Fantasy team creation and transfers.

Scoped deliberately: this covers roster ownership (pick players/coach within
the 100-credit budget) and transfers (unlimited, per the resolved OQ-4 -- see
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 6 -- so there's no wildcard
logic to implement either: wildcard existed specifically to bypass a transfer
limit that no longer exists). Lineup management (formation, bench/captain,
per-matchday scoring) is NOT here -- it depends on `players.position`, which
is null for every player right now (pending a reference file from the
project owner), so a formation's exact GK/OT/CF/CB slot counts can't be
validated. Team creation here only checks roster size (11 players + 1 coach)
and budget, not position mix.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_user
from app.schemas import RosterEntryOut, TeamCreateIn, TeamOut, TransferIn
from db.models import (
    Coach,
    EntityType,
    FantasyTeam,
    IdempotencyKey,
    League,
    LeagueVisibility,
    Matchday,
    MatchdayStatus,
    Player,
    Roster,
    Season,
    TransferAction,
    TransferHistoryEntry,
    User,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])

ROSTER_PLAYER_COUNT = 11  # 2 GK + 9 field players
BUDGET = 100.0


_IDEMPOTENCY_PENDING = 0  # sentinel response_status: claimed, business logic not finished yet


async def _claim_idempotency_key(
    db: AsyncSession, user_id: uuid.UUID, endpoint: str, key: str | None
) -> TeamOut | None:
    """
    Two-phase idempotency: claim first, fulfill (or release) after. Fixes two
    bugs the frontend session's review caught in the original single-phase
    version (main 5f03cac):

    1. The old version committed the business change, then wrote the
       idempotency record in a SEPARATE commit. A crash between the two left
       a successful operation with no replay record -- a retry would then
       404/409 instead of getting the original response back.
    2. The old version only checked "does a record exist" with no locking,
       so two concurrent requests with the same key could both see "no
       record" and both run the business logic.

    This function atomically INSERTs a pending placeholder (response_status
    = 0) as its own committed transaction, relying on the unique index on
    (user_id, endpoint, key) to let exactly one concurrent caller "win":
    - Insert succeeds -> returns None; caller proceeds, then MUST call
      _fulfill_idempotency_key (success) or _release_idempotency_key
      (client error) in the SAME transaction as its business writes, so the
      idempotency record and the operation commit or fail together.
    - Insert fails (another request already claimed this key) -> if that
      other request already finished, returns its stored response (a real
      replay); if it's still in flight, raises 409 so the caller retries
      shortly rather than racing it.

    Known gap: if a process crashes after claiming but before
    fulfilling/releasing, the placeholder is stuck at "pending" forever with
    nothing left to clean it up -- needs a background sweep (e.g. delete
    pending rows older than a few minutes) before this matters in practice.

    Known simplification: doesn't hash/compare the request body, so reusing
    the same key with a genuinely different payload silently replays the
    first response rather than 409ing on the mismatch. Fine as long as the
    frontend mints a fresh key per logical operation, not per click.
    """
    if key is None:
        return None

    db.add(IdempotencyKey(user_id=user_id, endpoint=endpoint, key=key, response_status=_IDEMPOTENCY_PENDING, response_body=""))
    try:
        await db.commit()
        return None  # claimed -- caller proceeds
    except IntegrityError:
        await db.rollback()

    existing = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint, IdempotencyKey.key == key
        )
    )
    if existing is None:
        return None  # lost a race with a since-released claim; safe to proceed
    if existing.response_status == _IDEMPOTENCY_PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A request with this Idempotency-Key is already in progress. Retry shortly.",
        )
    return TeamOut.model_validate_json(existing.response_body)


async def _fulfill_idempotency_key(
    db: AsyncSession, user_id: uuid.UUID, endpoint: str, key: str | None, status_code: int, body: TeamOut
) -> None:
    """Fill in a claimed placeholder with the real response. Caller commits
    this together with its own business writes -- not committed here."""
    if key is None:
        return
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint, IdempotencyKey.key == key
        )
    )
    if row is not None:
        row.response_status = status_code
        row.response_body = body.model_dump_json()


async def _release_idempotency_key(db: AsyncSession, user_id: uuid.UUID, endpoint: str, key: str | None) -> None:
    """Drop a claimed-but-never-fulfilled placeholder (the operation failed
    with a client error) so a retry with the same key -- e.g. after fixing a
    validation error -- isn't stuck behind a permanent 409."""
    if key is None:
        return
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.key == key,
            IdempotencyKey.response_status == _IDEMPOTENCY_PENDING,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.commit()


async def _get_active_season(db: AsyncSession, competition_id: uuid.UUID) -> Season:
    season = await db.scalar(
        select(Season).where(Season.competition_id == competition_id).order_by(Season.start_date.desc())
    )
    if season is None:
        raise HTTPException(status_code=404, detail="No season found for this competition")
    return season


async def _get_or_create_global_league(db: AsyncSession, season: Season) -> League:
    league = await db.scalar(select(League).where(League.season_id == season.id, League.admin_id.is_(None)))
    if league is None:
        league = League(season_id=season.id, name="Globalna liga", visibility=LeagueVisibility.PUBLIC)
        db.add(league)
        await db.flush()
    return league


async def _get_current_matchday_id(db: AsyncSession, season_id: uuid.UUID) -> uuid.UUID:
    """
    Best-effort "current" matchday to tag a transfer with: the first UPCOMING
    one, or -- since every season scraped so far is a completed historical
    one, not a live/ongoing season -- the last matchday overall as a
    fallback. transfer_history.matchday_id is NOT NULL in the original v1
    schema, so something must be provided even though "the current gameweek"
    isn't a meaningful concept for a finished season. Revisit once a live
    season with genuinely UPCOMING matchdays exists.
    """
    matchday = await db.scalar(
        select(Matchday)
        .where(Matchday.season_id == season_id, Matchday.status == MatchdayStatus.UPCOMING)
        .order_by(Matchday.number.asc())
    )
    if matchday is None:
        matchday = await db.scalar(
            select(Matchday).where(Matchday.season_id == season_id).order_by(Matchday.number.desc())
        )
    if matchday is None:
        raise HTTPException(404, "No matchdays found for this season")
    return matchday.id


async def _get_entity(db: AsyncSession, entity_type: str, entity_id: uuid.UUID):
    if entity_type == EntityType.PLAYER.value:
        return await db.get(Player, entity_id)
    if entity_type == EntityType.COACH.value:
        return await db.get(Coach, entity_id)
    return None


async def _roster_out(db: AsyncSession, team_id: uuid.UUID) -> list[RosterEntryOut]:
    """
    Batched, not N+1: one query for every player on the roster and one for
    every coach, instead of a separate round-trip per roster row (12 per
    team, previously) -- matters once this runs under real concurrent load,
    see docs/FRONTEND_BACKEND_HANDOFF.md performance plan.
    """
    result = await db.execute(select(Roster).where(Roster.fantasy_team_id == team_id))
    entries = result.scalars().all()

    player_ids = [r.entity_id for r in entries if r.entity_type == EntityType.PLAYER]
    coach_ids = [r.entity_id for r in entries if r.entity_type == EntityType.COACH]

    players_by_id: dict[uuid.UUID, Player] = {}
    if player_ids:
        rows = await db.execute(select(Player).where(Player.id.in_(player_ids)))
        players_by_id = {p.id: p for p in rows.scalars().all()}

    coaches_by_id: dict[uuid.UUID, Coach] = {}
    if coach_ids:
        rows = await db.execute(select(Coach).where(Coach.id.in_(coach_ids)))
        coaches_by_id = {c.id: c for c in rows.scalars().all()}

    out = []
    for r in entries:
        entity = (
            players_by_id.get(r.entity_id)
            if r.entity_type == EntityType.PLAYER
            else coaches_by_id.get(r.entity_id)
        )
        if entity is None:
            continue
        out.append(
            RosterEntryOut(
                entity_type=r.entity_type.value,
                entity_id=r.entity_id,
                name=entity.name,
                real_club=entity.real_club,
                purchase_price=float(r.purchase_price),
            )
        )
    return out


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreateIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamOut:
    endpoint = "POST /api/teams"
    claimed = await _claim_idempotency_key(db, current_user.id, endpoint, idempotency_key)
    if claimed is not None:
        return claimed

    try:
        if len(set(body.player_ids)) != ROSTER_PLAYER_COUNT:
            raise HTTPException(422, f"A roster must contain exactly {ROSTER_PLAYER_COUNT} distinct players")

        season = await _get_active_season(db, body.competition_id)
        league = await _get_or_create_global_league(db, season)

        # Note (frontend-session review, still open): this existence check and
        # the later INSERT aren't atomic with each other -- two truly
        # simultaneous requests with *different* idempotency keys (or none)
        # could both pass this check before either commits. The idempotency
        # claim above closes that hole for retries of the *same* logical
        # request; a duplicate-team race from two distinct requests would
        # need a unique constraint on (user_id, league_id) in fantasy_teams
        # to close fully. Not fixed here -- tracked as a follow-up.
        existing = await db.scalar(
            select(FantasyTeam).where(
                FantasyTeam.user_id == current_user.id, FantasyTeam.league_id == league.id
            )
        )
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "You already have a team in this league")

        result = await db.execute(select(Player).where(Player.id.in_(body.player_ids)))
        players = list(result.scalars().all())
        if len(players) != ROSTER_PLAYER_COUNT:
            raise HTTPException(422, "One or more players do not exist")
        if any(p.competition_id != body.competition_id for p in players):
            raise HTTPException(422, "All players must belong to the selected competition")

        coach = await db.get(Coach, body.coach_id)
        if coach is None or coach.competition_id != body.competition_id:
            raise HTTPException(422, "Coach not found for this competition")

        total_cost = float(sum(p.current_cost for p in players)) + float(coach.current_cost)
        if total_cost > BUDGET:
            raise HTTPException(422, f"Roster costs {total_cost:.2f} credits, budget is {BUDGET:.0f}")

        team = FantasyTeam(
            user_id=current_user.id,
            league_id=league.id,
            season_id=season.id,
            name=body.name,
            credit_balance=BUDGET - total_cost,
        )
        db.add(team)
        await db.flush()

        for p in players:
            db.add(
                Roster(
                    fantasy_team_id=team.id,
                    entity_type=EntityType.PLAYER,
                    entity_id=p.id,
                    purchase_price=p.current_cost,
                )
            )
        db.add(
            Roster(
                fantasy_team_id=team.id,
                entity_type=EntityType.COACH,
                entity_id=coach.id,
                purchase_price=coach.current_cost,
            )
        )
        await db.flush()

        result_out = TeamOut(
            id=team.id,
            league_id=team.league_id,
            season_id=team.season_id,
            name=team.name,
            credit_balance=float(team.credit_balance),
            total_points=float(team.total_points),
            wildcard_used=team.wildcard_used,
            roster=await _roster_out(db, team.id),
        )
        await _fulfill_idempotency_key(db, current_user.id, endpoint, idempotency_key, status.HTTP_201_CREATED, result_out)
        await db.commit()  # single atomic commit: team + roster + idempotency record together
        return result_out
    except HTTPException:
        await db.rollback()
        await _release_idempotency_key(db, current_user.id, endpoint, idempotency_key)
        raise


@router.get("/me", response_model=list[TeamOut])
async def list_my_teams(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[TeamOut]:
    result = await db.execute(select(FantasyTeam).where(FantasyTeam.user_id == current_user.id))
    teams = result.scalars().all()
    return [
        TeamOut(
            id=t.id,
            league_id=t.league_id,
            season_id=t.season_id,
            name=t.name,
            credit_balance=float(t.credit_balance),
            total_points=float(t.total_points),
            wildcard_used=t.wildcard_used,
            roster=await _roster_out(db, t.id),
        )
        for t in teams
    ]


@router.post("/{team_id}/transfers", response_model=TeamOut)
async def make_transfer(
    team_id: uuid.UUID,
    body: TransferIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamOut:
    endpoint = f"POST /api/teams/{team_id}/transfers"
    claimed = await _claim_idempotency_key(db, current_user.id, endpoint, idempotency_key)
    if claimed is not None:
        return claimed

    try:
        # Row-level lock on the team for the duration of this transaction --
        # two concurrent transfers on the same team must not both read the
        # same starting credit_balance (see docs, Section 5.4). The
        # idempotency claim above already serialized *retries of this same
        # request*; this lock guards against a *different* concurrent
        # transfer on the same team racing this one.
        team = await db.scalar(select(FantasyTeam).where(FantasyTeam.id == team_id).with_for_update())
        if team is None:
            raise HTTPException(404, "Team not found")
        if team.user_id != current_user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your team")

        try:
            drop_type = EntityType(body.drop_entity_type)
            add_type = EntityType(body.add_entity_type)
        except ValueError:
            raise HTTPException(422, "entity_type must be PLAYER or COACH")
        if drop_type != add_type:
            raise HTTPException(422, "Cannot swap a player for a coach or vice versa")

        roster_entry = await db.scalar(
            select(Roster).where(
                Roster.fantasy_team_id == team.id,
                Roster.entity_type == drop_type,
                Roster.entity_id == body.drop_entity_id,
            )
        )
        if roster_entry is None:
            raise HTTPException(404, "Player/coach to drop is not on this team")

        dropped = await _get_entity(db, drop_type.value, body.drop_entity_id)
        added = await _get_entity(db, add_type.value, body.add_entity_id)
        if added is None:
            raise HTTPException(422, "Player/coach to add does not exist")
        if added.competition_id != dropped.competition_id:
            raise HTTPException(422, "Replacement must be from the same competition")

        already_owned = await db.scalar(
            select(Roster).where(
                Roster.fantasy_team_id == team.id, Roster.entity_type == add_type, Roster.entity_id == added.id
            )
        )
        if already_owned is not None:
            raise HTTPException(422, "That player/coach is already on your team")

        sell_price = float(dropped.current_cost)
        buy_price = float(added.current_cost)
        new_balance = float(team.credit_balance) + sell_price - buy_price
        if new_balance < 0:
            raise HTTPException(422, f"Transfer would leave a negative balance ({new_balance:.2f} credits)")

        matchday_id = await _get_current_matchday_id(db, team.season_id)

        await db.delete(roster_entry)
        db.add(
            Roster(fantasy_team_id=team.id, entity_type=add_type, entity_id=added.id, purchase_price=buy_price)
        )
        db.add(
            TransferHistoryEntry(
                fantasy_team_id=team.id,
                matchday_id=matchday_id,
                action=TransferAction.SELL,
                entity_type=drop_type,
                entity_id=dropped.id,
                price=sell_price,
                credit_balance_after=float(team.credit_balance) + sell_price,
            )
        )
        db.add(
            TransferHistoryEntry(
                fantasy_team_id=team.id,
                matchday_id=matchday_id,
                action=TransferAction.BUY,
                entity_type=add_type,
                entity_id=added.id,
                price=buy_price,
                credit_balance_after=new_balance,
            )
        )
        team.credit_balance = new_balance
        await db.flush()

        result_out = TeamOut(
            id=team.id,
            league_id=team.league_id,
            season_id=team.season_id,
            name=team.name,
            credit_balance=float(team.credit_balance),
            total_points=float(team.total_points),
            wildcard_used=team.wildcard_used,
            roster=await _roster_out(db, team.id),
        )
        await _fulfill_idempotency_key(db, current_user.id, endpoint, idempotency_key, status.HTTP_200_OK, result_out)
        await db.commit()  # single atomic commit: transfer + idempotency record together
        return result_out
    except HTTPException:
        await db.rollback()
        await _release_idempotency_key(db, current_user.id, endpoint, idempotency_key)
        raise
