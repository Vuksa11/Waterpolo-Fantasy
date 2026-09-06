"""Owned, transactional fantasy teams. Prices and positions always come from DB."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_user
from app.routers.lineups import FORMATION_COUNTS
from app.schemas import RosterEntryOut, TeamCreateIn, TeamOut, TransferIn, SavedLineupIn, SavedLineupOut
from db.models import (Coach, EntityType, FantasyTeam, League, LeagueVisibility, Matchday,
                       MatchdayStatus, Player, Roster, Season, SeasonStatus, TransferAction,
                       TransferHistoryEntry, User, Lineup, Formation, Slot, SlotRole)

router = APIRouter(prefix='/api/teams', tags=['teams'])
BUDGET = Decimal('100.00')


def money(value):
    return Decimal(str(value))


def check_window(matchday):
    if matchday is None or matchday.status != MatchdayStatus.UPCOMING or matchday.deadline is None:
        raise HTTPException(409, 'No verified upcoming transfer/lineup deadline')
    deadline = matchday.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= datetime.now(timezone.utc):
        raise HTTPException(409, 'The matchday deadline has passed')


async def current_window(db, season_id):
    season = await db.get(Season, season_id)
    if season is None or season.status == SeasonStatus.FINISHED:
        raise HTTPException(409, 'Season is not open')
    # Do not skip an earlier round with an unknown or elapsed deadline.
    matchday = await db.scalar(select(Matchday).where(
        Matchday.season_id == season_id, Matchday.status == MatchdayStatus.UPCOMING
    ).order_by(Matchday.number, Matchday.id).limit(1).with_for_update(read=True))
    check_window(matchday)
    return matchday


async def owned_team(db, user, team_id, lock=False):
    query = select(FantasyTeam).where(FantasyTeam.id == team_id)
    if lock:
        query = query.with_for_update()
    team = await db.scalar(query)
    if team is None:
        raise HTTPException(404, 'Team not found')
    if team.user_id != user.id:
        raise HTTPException(403, 'Not your team')
    return team


async def team_outputs(db, teams):
    if not teams:
        return []
    team_ids = [team.id for team in teams]
    seasons = {s.id: s for s in (await db.execute(select(Season).where(
        Season.id.in_({team.season_id for team in teams})))).scalars()}
    entries = list((await db.execute(select(Roster).where(Roster.fantasy_team_id.in_(team_ids))
                                    .order_by(Roster.entity_type, Roster.entity_id))).scalars())
    entities = {}
    for kind, model in [(EntityType.PLAYER, Player), (EntityType.COACH, Coach)]:
        ids = [entry.entity_id for entry in entries if entry.entity_type == kind]
        if ids:
            entities.update({(kind, entity.id): entity for entity in
                             (await db.execute(select(model).where(model.id.in_(ids)))).scalars()})
    rosters = {team_id: [] for team_id in team_ids}
    for entry in entries:
        entity = entities.get((entry.entity_type, entry.entity_id))
        if entity is None:
            raise HTTPException(409, 'Roster references missing sports data')
        rosters[entry.fantasy_team_id].append(RosterEntryOut(
            entity_type=entry.entity_type, entity_id=entity.id, name=entity.name,
            real_club=entity.real_club, purchase_price=float(entry.purchase_price),
            current_cost=float(entity.current_cost), position=getattr(entity, 'position', None)))
    return [TeamOut(id=team.id, league_id=team.league_id, season_id=team.season_id,
                    competition_id=seasons[team.season_id].competition_id, version=team.version,
                    name=team.name, credit_balance=float(team.credit_balance),
                    total_points=float(team.total_points), wildcard_used=team.wildcard_used,
                    roster=rosters[team.id]) for team in teams]


@router.get('/me', response_model=list[TeamOut])
@router.get('', response_model=list[TeamOut])
async def list_my_teams(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teams = list((await db.execute(select(FantasyTeam).where(FantasyTeam.user_id == current_user.id)
                                  .order_by(FantasyTeam.id))).scalars())
    return await team_outputs(db, teams)


@router.post('', response_model=TeamOut, status_code=201)
async def create_team(body: TeamCreateIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if len(set(body.player_ids)) != 11:
        raise HTTPException(422, 'A roster must contain eleven distinct players')
    # Serialize global-league and per-user team creation on an existing row.
    season = await db.scalar(select(Season).where(Season.competition_id == body.competition_id)
                             .order_by(Season.start_date.desc(), Season.id).limit(1).with_for_update())
    if season is None:
        raise HTTPException(404, 'No season found')
    await current_window(db, season.id)
    league = await db.scalar(select(League).where(League.season_id == season.id, League.admin_id.is_(None)))
    if league is None:
        league = League(season_id=season.id, name='Globalna liga', visibility=LeagueVisibility.PUBLIC)
        db.add(league)
        await db.flush()
    existing = await db.scalar(select(FantasyTeam).where(FantasyTeam.user_id == current_user.id,
                                                        FantasyTeam.league_id == league.id))
    if existing:
        raise HTTPException(409, 'You already have a team in this league')
    players = list((await db.execute(select(Player).where(Player.id.in_(body.player_ids)))).scalars())
    if len(players) != 11 or any(p.competition_id != body.competition_id for p in players):
        raise HTTPException(422, 'All eleven players must exist in the selected competition')
    coach = await db.get(Coach, body.coach_id)
    if coach is None or coach.competition_id != body.competition_id:
        raise HTTPException(422, 'Coach not found for this competition')
    total = sum((money(p.current_cost) for p in players), money(coach.current_cost))
    if total > BUDGET:
        raise HTTPException(422, 'Roster exceeds the 100-credit budget')
    team = FantasyTeam(user_id=current_user.id, league_id=league.id, season_id=season.id,
                       name=body.name, credit_balance=BUDGET-total)
    db.add(team)
    await db.flush()
    for kind, entity in [(EntityType.PLAYER, p) for p in players] + [(EntityType.COACH, coach)]:
        db.add(Roster(fantasy_team_id=team.id, entity_type=kind, entity_id=entity.id, purchase_price=entity.current_cost))
    await db.commit()
    return (await team_outputs(db, [team]))[0]


@router.get('/{team_id}', response_model=TeamOut)
async def get_team(team_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await team_outputs(db, [await owned_team(db, current_user, team_id)]))[0]


@router.post('/{team_id}/transfers', response_model=TeamOut)
async def transfer(team_id: uuid.UUID, body: TransferIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    team = await owned_team(db, current_user, team_id, lock=True)
    matchday = await current_window(db, team.season_id)
    if body.drop_entity_type not in ('PLAYER', 'COACH') or body.drop_entity_type != body.add_entity_type:
        raise HTTPException(422, 'Swap must preserve PLAYER or COACH entity type')
    kind = EntityType(body.add_entity_type)
    model = Player if kind == EntityType.PLAYER else Coach
    entry = await db.scalar(select(Roster).where(Roster.fantasy_team_id == team.id,
                                                Roster.entity_type == kind, Roster.entity_id == body.drop_entity_id))
    if entry is None:
        raise HTTPException(422, 'Dropped entity is not owned')
    # Lock both price rows in UUID order for a consistent price snapshot.
    entities = {p.id: p for p in (await db.execute(select(model).where(
        model.id.in_([body.drop_entity_id, body.add_entity_id])).order_by(model.id).with_for_update(read=True))).scalars()}
    dropped, added = entities.get(body.drop_entity_id), entities.get(body.add_entity_id)
    season = await db.get(Season, team.season_id)
    if dropped is None or added is None or added.competition_id != season.competition_id:
        raise HTTPException(422, 'Replacement must exist in the team competition')
    if await db.scalar(select(Roster).where(Roster.fantasy_team_id == team.id,
                                            Roster.entity_type == kind, Roster.entity_id == added.id)):
        raise HTTPException(422, 'Replacement is already owned')
    sell, buy = money(dropped.current_cost), money(added.current_cost)
    balance = money(team.credit_balance) + sell - buy
    if balance < 0:
        raise HTTPException(422, 'Transfer exceeds available credits')
    await db.delete(entry)
    db.add(Roster(fantasy_team_id=team.id, entity_type=kind, entity_id=added.id, purchase_price=buy))
    for action, entity, price, after in [(TransferAction.SELL, dropped, sell, money(team.credit_balance)+sell),
                                        (TransferAction.BUY, added, buy, balance)]:
        db.add(TransferHistoryEntry(fantasy_team_id=team.id, matchday_id=matchday.id, action=action,
                                   entity_type=kind, entity_id=entity.id, price=price, credit_balance_after=after))
    team.credit_balance = balance
    team.version += 1
    # Existing saved future selections are now stale. Historical lineups remain.
    future_ids = select(Matchday.id).where(Matchday.season_id == team.season_id,
                                           Matchday.status == MatchdayStatus.UPCOMING,
                                           Matchday.deadline > datetime.now(timezone.utc))
    await db.execute(delete(Lineup).where(Lineup.fantasy_team_id == team.id, Lineup.matchday_id.in_(future_ids)))
    await db.commit()
    return (await team_outputs(db, [team]))[0]


async def lineup_output(db, team, matchday_id):
    matchday = await db.get(Matchday, matchday_id)
    if matchday is None or matchday.season_id != team.season_id:
        raise HTTPException(422, 'Matchday is not in the team season')
    rows = list((await db.execute(select(Lineup).where(Lineup.fantasy_team_id == team.id,
                                                      Lineup.matchday_id == matchday_id).order_by(Lineup.entity_id))).scalars())
    return SavedLineupOut(team_id=team.id, matchday_id=matchday_id, version=team.version,
                          formation=rows[0].formation if rows else None,
                          active_player_ids=[r.entity_id for r in rows if r.entity_type == EntityType.PLAYER and r.slot == Slot.ACTIVE],
                          bench_player_ids=[r.entity_id for r in rows if r.entity_type == EntityType.PLAYER and r.slot == Slot.BENCH],
                          captain_id=next((r.entity_id for r in rows if r.is_captain), None),
                          coach_id=next((r.entity_id for r in rows if r.entity_type == EntityType.COACH), None))


@router.get('/{team_id}/lineup', response_model=SavedLineupOut)
async def get_lineup(team_id: uuid.UUID, matchday_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await lineup_output(db, await owned_team(db, current_user, team_id), matchday_id)


@router.put('/{team_id}/lineup', response_model=SavedLineupOut)
async def save_lineup(team_id: uuid.UUID, matchday_id: uuid.UUID, body: SavedLineupIn,
                      current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    team = await owned_team(db, current_user, team_id, lock=True)
    if body.expected_version != team.version:
        raise HTTPException(409, 'Team changed; reload before saving')
    season = await db.get(Season, team.season_id)
    if season.status == SeasonStatus.FINISHED:
        raise HTTPException(409, 'Season is finished')
    matchday = await db.scalar(select(Matchday).where(Matchday.id == matchday_id).with_for_update(read=True))
    if matchday is None or matchday.season_id != team.season_id:
        raise HTTPException(422, 'Matchday is not in the team season')
    check_window(matchday)
    entries = list((await db.execute(select(Roster).where(Roster.fantasy_team_id == team.id))).scalars())
    player_ids = [r.entity_id for r in entries if r.entity_type == EntityType.PLAYER]
    coach_ids = [r.entity_id for r in entries if r.entity_type == EntityType.COACH]
    active = set(body.active_player_ids)
    if len(player_ids) != 11 or len(set(player_ids)) != 11 or len(coach_ids) != 1:
        raise HTTPException(422, 'Roster must contain eleven players and one coach')
    if len(active) != 7 or not active.issubset(player_ids) or body.captain_id not in active:
        raise HTTPException(422, 'Seven distinct owned starters and an active captain are required')
    players = list((await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars())
    coach = await db.get(Coach, coach_ids[0])
    if len(players) != 11 or coach is None or coach.competition_id != season.competition_id:
        raise HTTPException(422, 'Roster has missing or cross-competition entities')
    counts = dict.fromkeys(['GK', 'OT', 'CF', 'CB'], 0)
    bench = counts.copy()
    for player in players:
        if player.position not in counts or player.competition_id != season.competition_id:
            raise HTTPException(422, 'Every roster player needs a verified position in the team competition')
        (counts if player.id in active else bench)[player.position] += 1
    if counts != FORMATION_COUNTS[body.formation]:
        raise HTTPException(422, 'Starter positions do not match the formation')
    if bench['GK'] != 1 or bench['OT'] != 2 or bench['CF'] + bench['CB'] != 1:
        raise HTTPException(422, 'Bench requires one GK, two OT and one CF or CB')
    await db.execute(delete(Lineup).where(Lineup.fantasy_team_id == team.id, Lineup.matchday_id == matchday_id))
    for player in players:
        db.add(Lineup(fantasy_team_id=team.id, matchday_id=matchday_id, formation=Formation(body.formation),
                      entity_type=EntityType.PLAYER, entity_id=player.id,
                      slot=Slot.ACTIVE if player.id in active else Slot.BENCH,
                      slot_role=SlotRole(player.position), is_captain=player.id == body.captain_id))
    db.add(Lineup(fantasy_team_id=team.id, matchday_id=matchday_id, formation=Formation(body.formation),
                  entity_type=EntityType.COACH, entity_id=coach.id, slot=Slot.ACTIVE, slot_role=None))
    team.version += 1
    await db.commit()
    return await lineup_output(db, team, matchday_id)
