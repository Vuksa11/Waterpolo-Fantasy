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


BUDGET = 100.0  # kept in sync with app.routers.teams.BUDGET -- checked at import time below
assert BUDGET == __import__("app.routers.teams", fromlist=["BUDGET"]).BUDGET


@pytest_asyncio.fixture
async def roster_fixture(db_session):
    """
    Reuses real scraped data rather than synthetic fixtures (consistent with
    how every other check in this project has been verified against the real
    dev DB). But picking blindly "the first competition" (problemV11) doesn't
    guarantee an affordable roster -- a competition's cheapest 11 players +
    cheapest coach could exceed BUDGET depending on the current price data.
    So this scans every competition and picks the first one that actually has
    a full, affordable, distinct roster, and skips only if NONE of them do.

    problemV12 caught a further gap here: an affordable STARTING roster
    doesn't imply the specific transfer the tests perform (sell the most
    expensive of the 11, buy the cheapest spare player) is itself affordable
    -- e.g. 11 players at 8 + a 12-cost coach == 100 (fits), but selling an
    8-cost player to buy a 9-cost one leaves -1 credits, a real 422 that has
    nothing to do with the code under test. So `drop_player`/`extra_player`
    below are chosen explicitly to satisfy
    `starting_balance + drop.current_cost - extra.current_cost >= 0`, trying
    progressively more (cheap spare, then priciest-in-roster-to-sell)
    candidates before giving up on a competition.
    """
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

        spare_players = list(
            (
                await db_session.scalars(
                    select(Player)
                    .where(Player.competition_id == competition.id, Player.id.notin_([p.id for p in players]))
                    .order_by(Player.current_cost.asc(), Player.id.asc())
                    .limit(20)
                )
            ).all()
        )
        if not spare_players:
            continue

        roster_cost = sum(float(p.current_cost) for p in players) + float(coach.current_cost)
        if roster_cost > BUDGET:
            continue
        starting_balance = BUDGET - roster_cost

        # Try selling the most expensive roster player first (maximizes sell
        # proceeds), against every spare candidate cheapest-first, until one
        # transfer actually clears the budget check.
        drop_player = extra_player = None
        for candidate_drop in sorted(players, key=lambda p: -float(p.current_cost)):
            for candidate_extra in spare_players:
                if starting_balance + float(candidate_drop.current_cost) - float(candidate_extra.current_cost) >= 0:
                    drop_player, extra_player = candidate_drop, candidate_extra
                    break
            if drop_player is not None:
                break
        if drop_player is None:
            continue

        break
    else:
        pytest.skip("no competition in dev DB currently has an affordable roster AND an affordable test transfer")

    email = f"idempotency-test-{uuid.uuid4()}@example.com"
    user = User(email=email, password_hash="x", display_name="Idempotency Test")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    yield {
        "competition_id": competition.id,
        "players": players,
        "drop_player": drop_player,
        "extra_player": extra_player,
        "coach": coach,
        "user_id": user.id,
        "starting_balance": starting_balance,
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

    drop_id = str(roster_fixture["drop_player"].id)
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
    """
    problemV11 correctly pointed out the original version of this test
    asserted an exact [200, 409] split, which assumes the loser's re-check
    always lands while the winner's transaction is still "pending" -- that's
    likely given the winner needs several more DB round-trips first, but it's
    a real race between two genuine concurrent DB round-trips (asyncpg over
    the network), not a guaranteed ordering. [200, 200] (both see the final
    replayed result) is an equally valid outcome and must not fail the test.
    The actual invariant that must hold regardless of which interleaving
    happens: exactly one real transfer occurs, both 200 responses (if there
    are two) are byte-identical replays of it, and a same-key retry afterward
    doesn't create a second one.
    """
    token, resp = await _create_team(client, roster_fixture)
    assert resp.status_code == 201, resp.text
    team = resp.json()
    starting_balance = roster_fixture["starting_balance"]

    drop_player = roster_fixture["drop_player"]
    add_player = roster_fixture["extra_player"]
    drop_id = str(drop_player.id)
    add_id = str(add_player.id)
    sell_price = float(drop_player.current_cost)
    buy_price = float(add_player.current_cost)
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
    assert statuses in ([200, 409], [200, 200]), (r1.status_code, r1.text, r2.status_code, r2.text)

    successes = [r for r in (r1, r2) if r.status_code == 200]
    assert len(successes) >= 1, "at least one of the two concurrent requests must actually succeed"
    if len(successes) == 2:
        assert successes[0].json() == successes[1].json(), "two 200s must be identical replays, not two real transfers"

    expected_balance = round(starting_balance + sell_price - buy_price, 2)
    body = successes[0].json()
    assert body["credit_balance"] == pytest.approx(expected_balance, abs=0.01), body
    roster_entity_ids = {r["entity_id"] for r in body["roster"]}
    assert add_id in roster_entity_ids and drop_id not in roster_entity_ids, body["roster"]

    from db.models import FantasyTeam, TransferAction, TransferHistoryEntry

    entries = (
        await db_session.scalars(
            select(TransferHistoryEntry)
            .where(TransferHistoryEntry.fantasy_team_id == team["id"])
            .order_by(TransferHistoryEntry.action)
        )
    ).all()
    assert len(entries) == 2, "expected exactly one SELL + one BUY, found duplicates"
    by_action = {e.action: e for e in entries}
    assert set(by_action) == {TransferAction.SELL, TransferAction.BUY}
    assert by_action[TransferAction.SELL].entity_id == drop_player.id
    assert float(by_action[TransferAction.SELL].price) == pytest.approx(sell_price, abs=0.01)
    assert by_action[TransferAction.BUY].entity_id == add_player.id
    assert float(by_action[TransferAction.BUY].price) == pytest.approx(buy_price, abs=0.01)

    db_team = await db_session.get(FantasyTeam, uuid.UUID(team["id"]))
    assert float(db_team.credit_balance) == pytest.approx(expected_balance, abs=0.01)

    retry = await fire()
    assert retry.status_code == 200, retry.text
    assert retry.json() == successes[0].json(), "retry after settling must replay the exact same result"

    entries_after_retry = (
        await db_session.scalars(select(TransferHistoryEntry).where(TransferHistoryEntry.fantasy_team_id == team["id"]))
    ).all()
    assert len(entries_after_retry) == 2, "retry must not create additional history rows"


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
