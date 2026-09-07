"""
Regression tests for GET /api/competitions/{id}/leaderboard.

Runs against the real dev Postgres DB, like the rest of this project's
integration tests -- reuses whatever scraped player/coach data already
exists, creates its own user/team, cleans up after itself. A league for a
given competition may already exist from a prior run (it's created lazily
and persists) -- tests don't assume it's absent, only that a freshly
created team correctly appears in the ranking afterward.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from db.models import Coach, Competition, Player, User

pytestmark = pytest.mark.asyncio

BUDGET = 100.0


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import async_session

    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def team_fixture(db_session, client):
    """Registers a user and creates one affordable team, for asserting it
    shows up correctly in the leaderboard. Cleans itself up after."""
    competitions = list((await db_session.scalars(select(Competition))).all())
    if not competitions:
        pytest.skip("no scraped competition in dev DB -- run the scraper first")

    for competition in competitions:
        players = list(
            (
                await db_session.scalars(
                    select(Player)
                    .where(Player.competition_id == competition.id)
                    .order_by(Player.current_cost.asc(), Player.id.asc())
                    .limit(11)
                )
            ).all()
        )
        coach = await db_session.scalar(
            select(Coach).where(Coach.competition_id == competition.id).order_by(Coach.current_cost.asc())
        )
        if len(players) < 11 or coach is None:
            continue
        roster_cost = sum(float(p.current_cost) for p in players) + float(coach.current_cost)
        if roster_cost <= BUDGET:
            break
    else:
        pytest.skip("no competition in dev DB currently has an affordable 11-player + coach roster")

    email = f"leaderboard-test-{uuid.uuid4()}@example.com"
    user = User(email=email, password_hash="x", display_name="Leaderboard Test Owner")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.post(
        "/api/teams",
        json={
            "competition_id": str(competition.id),
            "name": "Leaderboard Test Team",
            "player_ids": [str(p.id) for p in players],
            "coach_id": str(coach.id),
        },
        headers={"Authorization": f"Bearer {_token_for(user.id)}"},
    )
    assert resp.status_code == 201, resp.text
    team = resp.json()

    yield {"competition_id": competition.id, "team": team, "user_id": user.id}

    from db.models import FantasyTeam, IdempotencyKey, Roster

    await db_session.execute(Roster.__table__.delete().where(Roster.fantasy_team_id == uuid.UUID(team["id"])))
    await db_session.execute(FantasyTeam.__table__.delete().where(FantasyTeam.id == uuid.UUID(team["id"])))
    await db_session.execute(IdempotencyKey.__table__.delete().where(IdempotencyKey.user_id == user.id))
    await db_session.execute(User.__table__.delete().where(User.id == user.id))
    await db_session.commit()


def _token_for(user_id: uuid.UUID) -> str:
    from app.core.security import create_access_token

    return create_access_token(user_id, 0)


async def _clear_leaderboard_cache(competition_id: uuid.UUID, limit: int = 50, offset: int = 0) -> None:
    """
    This endpoint caches by (competition_id, limit, offset) with TTL-only
    invalidation (same accepted simplification as standings/catalog -- no
    write invalidates it early). That's fine for real traffic but makes
    tests non-deterministic if REDIS_URL is set (it is, now that Redis is
    installed) and this exact key was already populated by an earlier test
    run within the last 30s: the assertion below would then see stale data
    missing the team THIS run just created. Clearing the key directly before
    asserting removes that flakiness without weakening what's tested -- the
    cache-hit path itself is already covered by backend/tests/test_cache.py.
    """
    from app.core.cache import _get_client, make_cache_key

    client = _get_client()
    if client is not None:
        await client.delete(make_cache_key("leaderboard:v2", competition_id=competition_id, limit=limit, offset=offset))


async def test_leaderboard_includes_created_team(client, team_fixture):
    competition_id = team_fixture["competition_id"]
    team = team_fixture["team"]

    await _clear_leaderboard_cache(competition_id)
    resp = await client.get(f"/api/competitions/{competition_id}/leaderboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["competition_id"] == str(competition_id)
    assert body["league_id"] is not None
    assert body["total"] >= 1

    entry = next((e for e in body["entries"] if e["team_id"] == team["id"]), None)
    assert entry is not None, "the just-created team must appear in its own league's leaderboard"
    assert entry["team_name"] == "Leaderboard Test Team"
    assert entry["owner_display_name"] == "Leaderboard Test Owner"
    assert entry["total_points"] == 0.0, "no scoring aggregation is wired up yet -- must be the default, not crash"
    assert isinstance(entry["rank"], int) and entry["rank"] >= 1


async def test_leaderboard_404_for_unknown_competition(client, db_session):
    """A competition_id that doesn't exist at all (no season, nothing) must
    404, not silently return an empty leaderboard -- that's reserved for a
    real competition with a season but no teams yet (untested here: would
    need a freshly-scraped competition with zero teams ever created, not
    worth constructing given how simple that code path is to read)."""
    from db.models import Competition as CompetitionModel

    fake_id = uuid.uuid4()
    # Guard against an astronomically unlikely real collision.
    exists = await db_session.get(CompetitionModel, fake_id)
    assert exists is None

    resp = await client.get(f"/api/competitions/{fake_id}/leaderboard")
    assert resp.status_code == 404, resp.text


async def test_leaderboard_pagination_validation(client, team_fixture):
    competition_id = team_fixture["competition_id"]

    resp = await client.get(f"/api/competitions/{competition_id}/leaderboard?limit=500")
    assert resp.status_code == 422

    resp = await client.get(f"/api/competitions/{competition_id}/leaderboard?offset=-1")
    assert resp.status_code == 422

    await _clear_leaderboard_cache(competition_id, limit=1, offset=0)
    resp = await client.get(f"/api/competitions/{competition_id}/leaderboard?limit=1&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()["entries"]) <= 1
