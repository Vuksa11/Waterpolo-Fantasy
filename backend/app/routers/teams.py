"""
Owned, transactional fantasy teams. Prices and positions always come from DB.

Lineup management (formation, bench/captain, deadline locking, optimistic
concurrency via `version`) lives here too, merged in from the frontend
session's branch. It depends on `players.position` and `matchdays.deadline`,
both null for every row in the current (fully historical, already-finished)
scraped season -- so `save_lineup`/`get_lineup`, and now `transfer` too
(see below), will correctly 422/409 on real data until the project owner's
reference file backfills positions and the scraper starts populating
deadlines. This is expected, not a bug: there is no meaningful "next
gameweek" to transfer into for a season that has already finished.

`transfer` calls `current_window`/`check_window` just like the lineup
routes (this merge's main branch had temporarily dropped that check to keep
transfers working against historical data with no deadlines -- but the
frontend branch's own test suite, test_teams.py, specifically asserts a
closed transfer window 409s, and that's the right call: a real fantasy
transfer should never be allowed once its gameweek is locked, whether or not
today's only available data happens to be a finished season). `create_team`
does NOT gate on a window, since a season being over shouldn't stop someone
from *building* a team, only from acting on it going forward.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_user
from app.routers.lineups import FORMATION_COUNTS
from app.schemas import RosterEntryOut, SavedLineupIn, SavedLineupOut, TeamCreateIn, TeamOut, TransferIn
from db.models import (
    Coach,
    EntityType,
    FantasyTeam,
    Formation,
    IdempotencyKey,
    League,
    LeagueVisibility,
    Lineup,
    Matchday,
    MatchdayStatus,
    Player,
    Roster,
    Season,
    SeasonStatus,
    Slot,
    SlotRole,
    TransferAction,
    TransferHistoryEntry,
    User,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])
BUDGET = Decimal("100.00")


def money(value) -> Decimal:
    return Decimal(str(value))


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

    Bugs found in a later review round (problemV9), fixed here: (a) if the
    conflicting row vanished between our failed INSERT and the re-read (its
    owner released it in the meantime), the old code returned None as if *we*
    had claimed it -- with no placeholder actually inserted, so a later
    fulfill() would silently update nothing, leaving no replay record at all.
    Now retries the claim itself instead of assuming it's safe to proceed
    unclaimed. (b) callers used to pass `current_user.id` directly here -- an
    ORM attribute access -- which is fine in THIS function specifically since
    it never rolls back the caller's transaction, but see the callers below
    for why they now capture `user_id` as a plain value up front instead.
    """
    if key is None:
        return None

    for _attempt in range(3):
        db.add(
            IdempotencyKey(
                user_id=user_id, endpoint=endpoint, key=key, response_status=_IDEMPOTENCY_PENDING, response_body=""
            )
        )
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
            continue  # the row we lost to vanished (its owner released it) -- try claiming it ourselves
        if existing.response_status == _IDEMPOTENCY_PENDING:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A request with this Idempotency-Key is already in progress. Retry shortly.",
            )
        return TeamOut.model_validate_json(existing.response_body)

    raise HTTPException(
        status.HTTP_409_CONFLICT, "Could not claim this Idempotency-Key after several attempts. Retry shortly."
    )


async def _fulfill_idempotency_key(
    db: AsyncSession, user_id: uuid.UUID, endpoint: str, key: str | None, status_code: int, body: TeamOut
) -> None:
    """Fill in a claimed placeholder with the real response. Caller commits
    this together with its own business writes -- not committed here.

    Raises if the row is missing rather than silently no-op'ing (problemV9):
    if `_claim_idempotency_key` returned None (claimed), this row must exist
    by construction -- a missing row here means something else deleted our
    claim underneath us, which should be loud, not swallowed.
    """
    if key is None:
        return
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint, IdempotencyKey.key == key
        )
    )
    if row is None:
        raise RuntimeError(f"Idempotency claim for {endpoint!r} disappeared before it could be fulfilled")
    row.response_status = status_code
    row.response_body = body.model_dump_json()


async def _release_idempotency_key(db: AsyncSession, user_id: uuid.UUID, endpoint: str, key: str | None) -> None:
    """Drop a claimed-but-never-fulfilled placeholder (the operation failed)
    so a retry with the same key -- e.g. after fixing a validation error --
    isn't stuck behind a permanent 409. Best-effort: swallows its own errors
    so a cleanup failure never masks the original exception that triggered
    it (callers run this from an `except` block).

    Known gap (problemV9/V10/V11, not fixed here): this only runs when the
    route handler's own exception handler executes. A killed process, or a
    cancellation/error during the claim's own commit (before this handler's
    try block even starts), can still leave a placeholder stuck at pending
    forever, 409ing every retry. Needs either a background sweep of old
    pending rows or a lease/TTL redesign before that failure mode is closed.
    """
    if key is None:
        return
    try:
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
    except Exception:
        await db.rollback()


def check_window(matchday: Matchday | None) -> None:
    if matchday is None or matchday.status != MatchdayStatus.UPCOMING or matchday.deadline is None:
        raise HTTPException(409, "No verified upcoming transfer/lineup deadline")
    deadline = matchday.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= datetime.now(timezone.utc):
        raise HTTPException(409, "The matchday deadline has passed")


async def current_window(db: AsyncSession, season_id: uuid.UUID) -> Matchday:
    season = await db.get(Season, season_id)
    if season is None or season.status == SeasonStatus.FINISHED:
        raise HTTPException(409, "Season is not open")
    # Do not skip an earlier round with an unknown or elapsed deadline.
    matchday = await db.scalar(
        select(Matchday)
        .where(Matchday.season_id == season_id, Matchday.status == MatchdayStatus.UPCOMING)
        .order_by(Matchday.number, Matchday.id)
        .limit(1)
        .with_for_update(read=True)
    )
    check_window(matchday)
    return matchday


async def owned_team(db: AsyncSession, user: User, team_id: uuid.UUID, lock: bool = False) -> FantasyTeam:
    query = select(FantasyTeam).where(FantasyTeam.id == team_id)
    if lock:
        query = query.with_for_update()
    team = await db.scalar(query)
    if team is None:
        raise HTTPException(404, "Team not found")
    if team.user_id != user.id:
        raise HTTPException(403, "Not your team")
    return team


async def team_outputs(db: AsyncSession, teams: list[FantasyTeam]) -> list[TeamOut]:
    """Batched, not N+1: one query for every player on the roster and one for
    every coach across ALL teams passed in, instead of a separate round-trip
    per roster row -- matters once this runs under real concurrent load, see
    docs/FRONTEND_BACKEND_HANDOFF.md performance plan."""
    if not teams:
        return []
    team_ids = [team.id for team in teams]
    seasons = {
        s.id: s
        for s in (
            await db.execute(select(Season).where(Season.id.in_({team.season_id for team in teams})))
        ).scalars()
    }
    entries = list(
        (
            await db.execute(
                select(Roster)
                .where(Roster.fantasy_team_id.in_(team_ids))
                .order_by(Roster.entity_type, Roster.entity_id)
            )
        ).scalars()
    )
    entities = {}
    for kind, model in [(EntityType.PLAYER, Player), (EntityType.COACH, Coach)]:
        ids = [entry.entity_id for entry in entries if entry.entity_type == kind]
        if ids:
            entities.update(
                {(kind, entity.id): entity for entity in (await db.execute(select(model).where(model.id.in_(ids)))).scalars()}
            )
    rosters: dict[uuid.UUID, list[RosterEntryOut]] = {team_id: [] for team_id in team_ids}
    for entry in entries:
        entity = entities.get((entry.entity_type, entry.entity_id))
        if entity is None:
            raise HTTPException(409, "Roster references missing sports data")
        rosters[entry.fantasy_team_id].append(
            RosterEntryOut(
                entity_type=entry.entity_type,
                entity_id=entity.id,
                name=entity.name,
                real_club=entity.real_club,
                purchase_price=float(entry.purchase_price),
                current_cost=float(entity.current_cost),
                position=getattr(entity, "position", None),
            )
        )
    return [
        TeamOut(
            id=team.id,
            league_id=team.league_id,
            season_id=team.season_id,
            competition_id=seasons[team.season_id].competition_id,
            version=team.version,
            name=team.name,
            credit_balance=float(team.credit_balance),
            total_points=float(team.total_points),
            wildcard_used=team.wildcard_used,
            roster=rosters[team.id],
        )
        for team in teams
    ]


@router.get("/me", response_model=list[TeamOut])
@router.get("", response_model=list[TeamOut])
async def list_my_teams(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[TeamOut]:
    teams = list(
        (
            await db.execute(select(FantasyTeam).where(FantasyTeam.user_id == current_user.id).order_by(FantasyTeam.id))
        ).scalars()
    )
    return await team_outputs(db, teams)


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> TeamOut:
    return (await team_outputs(db, [await owned_team(db, current_user, team_id)]))[0]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreateIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamOut:
    # Captured as a plain value up front, not read as `current_user.id` again
    # later -- problemV9 caught that `db.rollback()` expires loaded ORM
    # attributes even with expire_on_commit=False, and re-accessing one
    # afterward raises MissingGreenlet in async SQLAlchemy (reproduced
    # directly: a rollback'd row's .id access throws). Reading
    # `current_user.id` from inside the `except` block below, after this
    # function's own rollback, would turn an intended 4xx into an
    # unhandled 500 -- and skip releasing the idempotency claim entirely.
    user_id = current_user.id
    endpoint = "POST /api/teams"
    claimed = await _claim_idempotency_key(db, user_id, endpoint, idempotency_key)
    if claimed is not None:
        return claimed

    try:
        if len(set(body.player_ids)) != 11:
            raise HTTPException(422, "A roster must contain eleven distinct players")

        # Row-locked so two concurrent create_team calls for the same
        # competition can't both create a duplicate "Globalna liga".
        season = await db.scalar(
            select(Season)
            .where(Season.competition_id == body.competition_id)
            .order_by(Season.start_date.desc(), Season.id)
            .limit(1)
            .with_for_update()
        )
        if season is None:
            raise HTTPException(404, "No season found")

        league = await db.scalar(select(League).where(League.season_id == season.id, League.admin_id.is_(None)))
        if league is None:
            league = League(season_id=season.id, name="Globalna liga", visibility=LeagueVisibility.PUBLIC)
            db.add(league)
            await db.flush()

        # Correction (an independent review, Codex, problemV15, caught this
        # comment was stale after the frontend-branch merge): this existence
        # check is NOT actually racy against a truly simultaneous distinct
        # request the way it used to be documented. The `with_for_update()`
        # season lock above is held for the rest of this transaction (until
        # commit/rollback), so a second concurrent create_team call for the
        # SAME season blocks at that SELECT until the first one finishes --
        # it then sees the first request's committed team and correctly
        # 409s here, rather than both passing this check simultaneously.
        # This is a wider-than-necessary side effect of a lock taken for a
        # different reason (serializing per season, not per league), and
        # it's part of why concurrent create_team calls show up as write
        # contention under load (see docs/FRONTEND_BACKEND_HANDOFF.md,
        # performance plan) -- if that lock is ever narrowed or replaced
        # (e.g. a partial unique index on leagues, discussed there), this
        # existence check's uniqueness guarantee must be preserved some
        # other way (a unique constraint on (user_id, league_id) in
        # fantasy_teams, with the resulting IntegrityError handled, is the
        # natural replacement) -- not silently reopened.
        existing = await db.scalar(
            select(FantasyTeam).where(FantasyTeam.user_id == user_id, FantasyTeam.league_id == league.id)
        )
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "You already have a team in this league")

        players = list((await db.execute(select(Player).where(Player.id.in_(body.player_ids)))).scalars())
        if len(players) != 11:
            raise HTTPException(422, "One or more players do not exist")
        if any(p.competition_id != body.competition_id for p in players):
            raise HTTPException(422, "All players must belong to the selected competition")

        coach = await db.get(Coach, body.coach_id)
        if coach is None or coach.competition_id != body.competition_id:
            raise HTTPException(422, "Coach not found for this competition")

        total = sum((money(p.current_cost) for p in players), money(coach.current_cost))
        if total > BUDGET:
            raise HTTPException(422, f"Roster costs {total} credits, budget is {BUDGET}")

        team = FantasyTeam(
            user_id=user_id, league_id=league.id, season_id=season.id, name=body.name, credit_balance=BUDGET - total
        )
        db.add(team)
        await db.flush()

        for kind, entity in [(EntityType.PLAYER, p) for p in players] + [(EntityType.COACH, coach)]:
            db.add(
                Roster(fantasy_team_id=team.id, entity_type=kind, entity_id=entity.id, purchase_price=entity.current_cost)
            )
        await db.flush()

        result_out = (await team_outputs(db, [team]))[0]
        await _fulfill_idempotency_key(db, user_id, endpoint, idempotency_key, status.HTTP_201_CREATED, result_out)
        await db.commit()  # single atomic commit: team + roster + idempotency record together
        return result_out
    except (Exception, asyncio.CancelledError):
        # Not `except HTTPException` -- problemV9 pointed out a plain
        # HTTPException-only catch leaves the idempotency claim stuck at
        # "pending" forever for any OTHER exception (a bug, a DB error), not
        # just a process crash. `asyncio.CancelledError` is listed explicitly
        # alongside `Exception` -- problemV10 pointed out it's a BaseException
        # subclass (since Python 3.8), so a bare `except Exception` silently
        # skips it, and a cancelled task (client disconnect, server shutdown)
        # would leave the claim stuck at "pending" forever with no release.
        # Still doesn't fully solve the gap: a hard process crash (kill -9)
        # runs no exception handler at all, so nothing here recovers that --
        # see _release_idempotency_key's docstring; that needs a background
        # sweep/lease, tracked separately, not fixed by this except clause.
        await db.rollback()
        await _release_idempotency_key(db, user_id, endpoint, idempotency_key)
        raise


@router.post("/{team_id}/transfers", response_model=TeamOut)
async def make_transfer(
    team_id: uuid.UUID,
    body: TransferIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamOut:
    # Captured before any DB work so it's never touched after a possible
    # rollback below -- see create_team's comment / problemV9 (MissingGreenlet:
    # accessing an ORM attribute post-rollback raises in async SQLAlchemy).
    user_id = current_user.id
    endpoint = f"POST /api/teams/{team_id}/transfers"
    claimed = await _claim_idempotency_key(db, user_id, endpoint, idempotency_key)
    if claimed is not None:
        return claimed

    try:
        # Row-level lock on the team for the duration of this transaction --
        # two concurrent transfers on the same team must not both read the
        # same starting credit_balance. The idempotency claim above already
        # serialized *retries of this same request*; this lock guards
        # against a *different* concurrent transfer on the same team racing
        # this one.
        team = await db.scalar(select(FantasyTeam).where(FantasyTeam.id == team_id).with_for_update())
        if team is None:
            raise HTTPException(404, "Team not found")
        if team.user_id != user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your team")

        if body.drop_entity_type not in ("PLAYER", "COACH") or body.drop_entity_type != body.add_entity_type:
            raise HTTPException(422, "Cannot swap a player for a coach or vice versa")
        kind = EntityType(body.add_entity_type)
        model = Player if kind == EntityType.PLAYER else Coach

        roster_entry = await db.scalar(
            select(Roster).where(
                Roster.fantasy_team_id == team.id, Roster.entity_type == kind, Roster.entity_id == body.drop_entity_id
            )
        )
        if roster_entry is None:
            raise HTTPException(422, "Player/coach to drop is not on this team")

        # Lock both price rows (in a fixed UUID order, so two transfers that
        # both touch the same pair of entities can't deadlock each other) for
        # a consistent price snapshot -- a concurrent price-recalculation
        # write can't change the numbers mid-transfer.
        entities = {
            e.id: e
            for e in (
                await db.execute(
                    select(model)
                    .where(model.id.in_([body.drop_entity_id, body.add_entity_id]))
                    .order_by(model.id)
                    .with_for_update(read=True)
                )
            ).scalars()
        }
        dropped, added = entities.get(body.drop_entity_id), entities.get(body.add_entity_id)
        if added is None:
            raise HTTPException(422, "Player/coach to add does not exist")
        if dropped is None or added.competition_id != dropped.competition_id:
            raise HTTPException(422, "Replacement must be from the same competition")

        already_owned = await db.scalar(
            select(Roster).where(Roster.fantasy_team_id == team.id, Roster.entity_type == kind, Roster.entity_id == added.id)
        )
        if already_owned is not None:
            raise HTTPException(422, "That player/coach is already on your team")

        sell_price = money(dropped.current_cost)
        buy_price = money(added.current_cost)
        new_balance = money(team.credit_balance) + sell_price - buy_price
        if new_balance < 0:
            raise HTTPException(422, f"Transfer would leave a negative balance ({new_balance} credits)")

        matchday = await current_window(db, team.season_id)
        matchday_id = matchday.id

        await db.delete(roster_entry)
        db.add(Roster(fantasy_team_id=team.id, entity_type=kind, entity_id=added.id, purchase_price=buy_price))
        db.add(
            TransferHistoryEntry(
                fantasy_team_id=team.id,
                matchday_id=matchday_id,
                action=TransferAction.SELL,
                entity_type=kind,
                entity_id=dropped.id,
                price=sell_price,
                credit_balance_after=money(team.credit_balance) + sell_price,
            )
        )
        db.add(
            TransferHistoryEntry(
                fantasy_team_id=team.id,
                matchday_id=matchday_id,
                action=TransferAction.BUY,
                entity_type=kind,
                entity_id=added.id,
                price=buy_price,
                credit_balance_after=new_balance,
            )
        )
        team.credit_balance = new_balance
        team.version += 1
        # Existing saved future selections are now stale (they may reference
        # the entity just dropped). Historical lineups remain untouched.
        future_ids = select(Matchday.id).where(
            Matchday.season_id == team.season_id,
            Matchday.status == MatchdayStatus.UPCOMING,
            Matchday.deadline > datetime.now(timezone.utc),
        )
        await db.execute(delete(Lineup).where(Lineup.fantasy_team_id == team.id, Lineup.matchday_id.in_(future_ids)))
        await db.flush()

        result_out = (await team_outputs(db, [team]))[0]
        await _fulfill_idempotency_key(db, user_id, endpoint, idempotency_key, status.HTTP_200_OK, result_out)
        await db.commit()  # single atomic commit: transfer + idempotency record together
        return result_out
    except (Exception, asyncio.CancelledError):
        # Not `except HTTPException` -- problemV9 pointed out a plain
        # HTTPException-only catch leaves the idempotency claim stuck at
        # "pending" forever for any OTHER exception (a bug, a DB error), not
        # just a process crash. `asyncio.CancelledError` is listed explicitly
        # alongside `Exception` -- problemV10 pointed out it's a BaseException
        # subclass (since Python 3.8), so a bare `except Exception` silently
        # skips it, and a cancelled task (client disconnect, server shutdown)
        # would leave the claim stuck at "pending" forever with no release.
        # Still doesn't fully solve the gap: a hard process crash (kill -9)
        # runs no exception handler at all, so nothing here recovers that --
        # see _release_idempotency_key's docstring; that needs a background
        # sweep/lease, tracked separately, not fixed by this except clause.
        await db.rollback()
        await _release_idempotency_key(db, user_id, endpoint, idempotency_key)
        raise


async def lineup_output(db: AsyncSession, team: FantasyTeam, matchday_id: uuid.UUID) -> SavedLineupOut:
    matchday = await db.get(Matchday, matchday_id)
    if matchday is None or matchday.season_id != team.season_id:
        raise HTTPException(422, "Matchday is not in the team season")
    rows = list(
        (
            await db.execute(
                select(Lineup)
                .where(Lineup.fantasy_team_id == team.id, Lineup.matchday_id == matchday_id)
                .order_by(Lineup.entity_id)
            )
        ).scalars()
    )
    return SavedLineupOut(
        team_id=team.id,
        matchday_id=matchday_id,
        version=team.version,
        formation=rows[0].formation if rows else None,
        active_player_ids=[r.entity_id for r in rows if r.entity_type == EntityType.PLAYER and r.slot == Slot.ACTIVE],
        bench_player_ids=[r.entity_id for r in rows if r.entity_type == EntityType.PLAYER and r.slot == Slot.BENCH],
        captain_id=next((r.entity_id for r in rows if r.is_captain), None),
        coach_id=next((r.entity_id for r in rows if r.entity_type == EntityType.COACH), None),
    )


@router.get("/{team_id}/lineup", response_model=SavedLineupOut)
async def get_lineup(
    team_id: uuid.UUID, matchday_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SavedLineupOut:
    return await lineup_output(db, await owned_team(db, current_user, team_id), matchday_id)


@router.put("/{team_id}/lineup", response_model=SavedLineupOut)
async def save_lineup(
    team_id: uuid.UUID,
    matchday_id: uuid.UUID,
    body: SavedLineupIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedLineupOut:
    team = await owned_team(db, current_user, team_id, lock=True)
    if body.expected_version != team.version:
        raise HTTPException(409, "Team changed; reload before saving")
    season = await db.get(Season, team.season_id)
    if season.status == SeasonStatus.FINISHED:
        raise HTTPException(409, "Season is finished")
    matchday = await db.scalar(select(Matchday).where(Matchday.id == matchday_id).with_for_update(read=True))
    if matchday is None or matchday.season_id != team.season_id:
        raise HTTPException(422, "Matchday is not in the team season")
    check_window(matchday)
    entries = list((await db.execute(select(Roster).where(Roster.fantasy_team_id == team.id))).scalars())
    player_ids = [r.entity_id for r in entries if r.entity_type == EntityType.PLAYER]
    coach_ids = [r.entity_id for r in entries if r.entity_type == EntityType.COACH]
    active = set(body.active_player_ids)
    if len(player_ids) != 11 or len(set(player_ids)) != 11 or len(coach_ids) != 1:
        raise HTTPException(422, "Roster must contain eleven players and one coach")
    if len(active) != 7 or not active.issubset(player_ids) or body.captain_id not in active:
        raise HTTPException(422, "Seven distinct owned starters and an active captain are required")
    players = list((await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars())
    coach = await db.get(Coach, coach_ids[0])
    if len(players) != 11 or coach is None or coach.competition_id != season.competition_id:
        raise HTTPException(422, "Roster has missing or cross-competition entities")
    counts = dict.fromkeys(["GK", "OT", "CF", "CB"], 0)
    bench = counts.copy()
    for player in players:
        if player.position not in counts or player.competition_id != season.competition_id:
            raise HTTPException(422, "Every roster player needs a verified position in the team competition")
        (counts if player.id in active else bench)[player.position] += 1
    if counts != FORMATION_COUNTS[body.formation]:
        raise HTTPException(422, "Starter positions do not match the formation")
    if bench["GK"] != 1 or bench["OT"] != 2 or bench["CF"] + bench["CB"] != 1:
        raise HTTPException(422, "Bench requires one GK, two OT and one CF or CB")
    await db.execute(delete(Lineup).where(Lineup.fantasy_team_id == team.id, Lineup.matchday_id == matchday_id))
    for player in players:
        db.add(
            Lineup(
                fantasy_team_id=team.id,
                matchday_id=matchday_id,
                formation=Formation(body.formation),
                entity_type=EntityType.PLAYER,
                entity_id=player.id,
                slot=Slot.ACTIVE if player.id in active else Slot.BENCH,
                slot_role=SlotRole(player.position),
                is_captain=player.id == body.captain_id,
            )
        )
    db.add(
        Lineup(
            fantasy_team_id=team.id,
            matchday_id=matchday_id,
            formation=Formation(body.formation),
            entity_type=EntityType.COACH,
            entity_id=coach.id,
            slot=Slot.ACTIVE,
            slot_role=None,
        )
    )
    team.version += 1
    await db.commit()
    return await lineup_output(db, team, matchday_id)
