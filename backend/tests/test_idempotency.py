"""
Regression tests for the idempotency-key handling in app/routers/teams.py.

These persist in the repo per problemV10 (frontend-session review): manual
curl checks and throwaway scratch scripts caught real bugs across V8-V10 but
aren't a substitute for tests that keep running afterward.

Runs against the real local dev Postgres DB (this project has no sqlite/mock
DB layer -- everything else in the codebase is tested that way too), reusing
whatever competition/player/coach data already exists from the scraper and
cleaning up every row it creates. If the dev DB hasn't been scraped yet, the
integration tests skip rather than fail (there's nothing to build a roster
from), but the CancelledError unit test always runs since it needs no DB.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from db.models import Coach, Competition, Player, User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_after_test():
    """
    The app's asyncpg connection pool (app.core.db.engine) is a module-level
    singleton created once on import. pytest-asyncio gives each test its own
    event loop by default, but a pooled connection stays bound to whichever
    loop created it -- reused in the next test's *different* loop, that raises
    "attached to a different loop". Disposing the pool after every test forces
    fresh connections on whatever loop runs next, without touching the app's
    actual engine setup (which is correct for real, single-event-loop use).
    """
    yield
    from app.core.db import engine

    await engine.dispose()


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
async def roster_fixture(db_session):
    """Reuses real scraped data (any competition with >=11 players + 1 coach)."""
    competition = await db_session.scalar(select(Competition).limit(1))
    if competition is None:
        pytest.skip("no scraped competition in dev DB -- run the scraper first")

    players = list(
        (
            await db_session.scalars(
                select(Player).where(Player.competition_id == competition.id).order_by(Player.current_cost.asc()).limit(11)
            )
        ).all()
    )
    coach = await db_session.scalar(select(Coach).where(Coach.competition_id == competition.id))
    if len(players) < 11 or coach is None:
        pytest.skip("dev DB doesn't have enough players/coaches for a full roster yet")

    extra_player = await db_session.scalar(
        select(Player).where(
            Player.competition_id == competition.id,
            Player.id.notin_([p.id for p in players]),
        )
    )
    if extra_player is None:
        pytest.skip("dev DB has no spare player to transfer in")

    email = f"idempotency-test-{uuid.uuid4()}@example.com"
    user = User(email=email, password_hash="x", display_name="Idempotency Test")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    yield {
        "competition_id": competition.id,
        "players": players,
        "extra_player": extra_player,
        "coach": coach,
        "user_id": user.id,
    }

    # Cleanup: delete anything this test created, in FK-safe order.
    from db.models import FantasyTeam, IdempotencyKey, Roster, TransferHistoryEntry

    team_ids = list((await db_session.scalars(select(FantasyTeam.id).where(FantasyTeam.user_id == user.id))).all())
    for team_id in team_ids:
        await db_session.execute(
            TransferHistoryEntry.__table__.delete().where(TransferHistoryEntry.fantasy_team_id == team_id)
        )
        await db_session.execute(Roster.__table__.delete().where(Roster.fantasy_team_id == team_id))
    await db_session.execute(FantasyTeam.__table__.delete().where(FantasyTeam.user_id == user.id))
    await db_session.execute(IdempotencyKey.__table__.delete().where(IdempotencyKey.user_id == user.id))
    await db_session.execute(User.__table__.delete().where(User.id == user.id))
    await db_session.commit()


def _token_for(user_id: uuid.UUID) -> str:
    from app.core.security import create_access_token

    return create_access_token(user_id)


async def _create_team(client, roster_fixture):
    token = _token_for(roster_fixture["user_id"])
    body = {
        "competition_id": str(roster_fixture["competition_id"]),
        "name": "Idempotency Test Team",
        "player_ids": [str(p.id) for p in roster_fixture["players"]],
        "coach_id": str(roster_fixture["coach"].id),
    }
    resp = await client.post("/api/teams", json=body, headers={"Authorization": f"Bearer {token}"})
    return token, resp


async def test_create_team_and_transfer_succeed(client, roster_fixture):
    token, resp = await _create_team(client, roster_fixture)
    assert resp.status_code == 201, resp.text
    team = resp.json()

    drop_id = str(roster_fixture["players"][0].id)
    add_id = str(roster_fixture["extra_player"].id)
    resp = await client.post(
        f"/api/teams/{team['id']}/transfers",
        json={
            "drop_entity_type": "PLAYER",
            "drop_entity_id": drop_id,
            "add_entity_type": "PLAYER",
            "add_entity_id": add_id,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "normal-transfer"},
    )
    assert resp.status_code == 200, resp.text


async def test_invalid_transfer_releases_idempotency_claim(client, roster_fixture, db_session):
    token, resp = await _create_team(client, roster_fixture)
    assert resp.status_code == 201, resp.text
    team = resp.json()

    fake_id = str(uuid.uuid4())
    key = f"invalid-{uuid.uuid4()}"
    resp = await client.post(
        f"/api/teams/{team['id']}/transfers",
        json={
            "drop_entity_type": "PLAYER",
            "drop_entity_id": fake_id,
            "add_entity_type": "PLAYER",
            "add_entity_id": fake_id,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 404, resp.text

    from db.models import IdempotencyKey

    stuck = await db_session.scalar(select(IdempotencyKey).where(IdempotencyKey.key == key))
    assert stuck is None, "idempotency claim was left stuck at pending instead of being released"

    # Retrying the same key must re-execute cleanly, not hang on a phantom claim.
    resp = await client.post(
        f"/api/teams/{team['id']}/transfers",
        json={
            "drop_entity_type": "PLAYER",
            "drop_entity_id": fake_id,
            "add_entity_type": "PLAYER",
            "add_entity_id": fake_id,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 404, resp.text


async def test_concurrent_same_key_transfer_serializes(client, roster_fixture, db_session):
    token, resp = await _create_team(client, roster_fixture)
    assert resp.status_code == 201, resp.text
    team = resp.json()

    drop_id = str(roster_fixture["players"][0].id)
    add_id = str(roster_fixture["extra_player"].id)
    key = f"race-{uuid.uuid4()}"

    async def fire():
        return await client.post(
            f"/api/teams/{team['id']}/transfers",
            json={
                "drop_entity_type": "PLAYER",
                "drop_entity_id": drop_id,
                "add_entity_type": "PLAYER",
                "add_entity_id": add_id,
            },
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        )

    r1, r2 = await asyncio.gather(fire(), fire())
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], (r1.status_code, r1.text, r2.status_code, r2.text)

    from db.models import TransferHistoryEntry

    entries = (
        await db_session.scalars(select(TransferHistoryEntry).where(TransferHistoryEntry.fantasy_team_id == team["id"]))
    ).all()
    assert len(entries) == 2, "expected exactly one SELL + one BUY, found duplicates"

    retry = await fire()
    assert retry.status_code == 200, retry.text


async def test_cancelled_task_still_releases_claim():
    """
    Deterministic unit test for the problemV10 gap: asyncio.CancelledError is
    a BaseException subclass (Python 3.8+), so a bare `except Exception`
    silently skips it, leaving the idempotency claim stuck at "pending"
    forever if the request task is cancelled (client disconnect, server
    shutdown) mid-transaction. Uses mocked DB/helper dependencies for
    deterministic fault injection, the same technique the frontend session
    used to originally find this gap -- no timing/race dependency, so this
    can't be flaky.
    """
    import app.routers.teams as teams_mod

    db = MagicMock()
    db.rollback = AsyncMock()

    with patch.object(teams_mod, "_claim_idempotency_key", AsyncMock(return_value=None)), patch.object(
        teams_mod, "_release_idempotency_key", AsyncMock()
    ) as release, patch.object(teams_mod, "_fulfill_idempotency_key", AsyncMock()), patch.object(
        teams_mod, "_get_active_season", AsyncMock(side_effect=asyncio.CancelledError())
    ):
        current_user = MagicMock()
        current_user.id = uuid.uuid4()
        body = MagicMock()
        body.player_ids = [uuid.uuid4() for _ in range(11)]
        body.competition_id = uuid.uuid4()

        with pytest.raises(asyncio.CancelledError):
            await teams_mod.create_team(body=body, idempotency_key="cancel-test", current_user=current_user, db=db)

        assert release.await_count == 1, "cancellation must still release the idempotency claim"
        assert db.rollback.await_count == 1
