"""
Baseline load test -- "measure before optimizing" per the performance plan
in docs/FRONTEND_BACKEND_HANDOFF.md. Weighted toward reads (browsing home/
standings/catalog, which is most real traffic for a fantasy app) with a
smaller share of writes (register, create team, transfer, lineup, retries).

Run `.venv/bin/python -m backend.loadtest.prepare_upcoming_matchday` FIRST --
every real matchday in the dev DB is a finished historical round with no
deadline, so without a test-only UPCOMING+future-deadline matchday every
transfer/lineup write 409s immediately (fast, but doesn't exercise the
write-lock/contention paths this profile exists to measure). Clean up after
with `--cleanup`.

Run: .venv/bin/locust -f backend/loadtest/locustfile.py --host http://127.0.0.1:8001
Headless example (200 users, spawn 20/s, 60s):
  .venv/bin/locust -f backend/loadtest/locustfile.py --host http://127.0.0.1:8001 \
    --headless -u 200 -r 20 -t 60s --csv=backend/loadtest/results/run1

This is a single dev laptop hitting a single dev Postgres (max_connections=100)
running one uvicorn process -- it measures per-request latency and
correctness under load, not literally "1000 concurrent" (that needs the
multi-worker + PgBouncer deployment from Phase 3 to even be reachable). Real
production-scale validation happens after that deployment exists.

problemV10/V12/V14 (frontend-session reviews) correctly pointed out earlier
versions of this file had no transfer/lineup/concurrent-retry profile at
all -- RegisteringUser now continues past team creation into repeated
transfers and a lineup save attempt (expected to 422 on unverified
positions -- that's still a real code path worth measuring, not a test
bug), and IdempotencyRetryUser specifically measures the replay path (same
Idempotency-Key sent twice in a row, simulating a client retrying after a
timeout) rather than only ever sending fresh keys.
"""

import random
import uuid

from locust import HttpUser, between, task

COMPETITION_ID = "5f3467a2-efb5-43df-b9cf-5005b27fcf85"  # Regionalna liga


class BrowsingUser(HttpUser):
    """Most traffic: anonymous visitors browsing sports data. No auth needed."""

    weight = 8
    wait_time = between(1, 3)

    @task(5)
    def home(self):
        self.client.get(f"/api/home?competition_id={COMPETITION_ID}", name="/api/home")

    @task(4)
    def standings(self):
        self.client.get(
            f"/api/competitions/{COMPETITION_ID}/standings", name="/api/competitions/:id/standings"
        )

    @task(4)
    def catalog(self):
        offset = random.choice([0, 24, 48, 72])
        sort = random.choice(["cost_desc", "cost_asc", "name_asc"])
        self.client.get(
            f"/api/players/catalog?competition_id={COMPETITION_ID}&limit=24&offset={offset}&sort={sort}",
            name="/api/players/catalog",
        )

    @task(2)
    def facets(self):
        self.client.get(f"/api/players/facets?competition_id={COMPETITION_ID}", name="/api/players/facets")

    @task(1)
    def matchdays(self):
        self.client.get(
            f"/api/competitions/{COMPETITION_ID}/matchdays", name="/api/competitions/:id/matchdays"
        )


class RegisteringUser(HttpUser):
    """A smaller share of traffic: new users registering, building a team,
    then making a few transfers and one lineup-save attempt -- exercises the
    full write path, not just team creation."""

    weight = 1
    wait_time = between(2, 5)

    def on_start(self):
        email = f"loadtest-{uuid.uuid4().hex[:12]}@example.com"
        resp = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "loadtest123", "display_name": "Load Test"},
            name="/api/auth/register",
        )
        self.token = resp.json().get("access_token") if resp.status_code == 201 else None
        self.team = None
        self.owned_ids = set()

    @task
    def create_team_attempt(self):
        if not self.token or self.team is not None:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        players_resp = self.client.get(
            f"/api/players?competition_id={COMPETITION_ID}", name="/api/players", headers=headers
        )
        if players_resp.status_code != 200:
            return
        all_players = players_resp.json()
        players = sorted(all_players, key=lambda p: p["current_cost"])[:11]
        if len(players) < 11:
            return
        coaches_resp = self.client.get(
            f"/api/coaches?competition_id={COMPETITION_ID}", name="/api/coaches", headers=headers
        )
        coaches = coaches_resp.json()
        if not coaches:
            return
        resp = self.client.post(
            "/api/teams",
            json={
                "competition_id": COMPETITION_ID,
                "name": "Load Test Team",
                "player_ids": [p["id"] for p in players],
                "coach_id": coaches[0]["id"],
            },
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            name="/api/teams [POST]",
        )
        if resp.status_code == 201:
            self.team = resp.json()
            self.owned_ids = {r["entity_id"] for r in self.team["roster"] if r["entity_type"] == "PLAYER"}
            self._all_players = all_players

    @task(3)
    def transfer_attempt(self):
        """A real transfer (needs prepare_upcoming_matchday.py's test
        matchday to succeed instead of a fast 409 -- both are real code
        paths worth measuring)."""
        if self.team is None:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        spare = next((p for p in self._all_players if p["id"] not in self.owned_ids), None)
        if spare is None:
            return
        drop_id = next(iter(self.owned_ids))
        resp = self.client.post(
            f"/api/teams/{self.team['id']}/transfers",
            json={
                "drop_entity_type": "PLAYER",
                "drop_entity_id": drop_id,
                "add_entity_type": "PLAYER",
                "add_entity_id": spare["id"],
            },
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            name="/api/teams/:id/transfers [POST]",
        )
        if resp.status_code == 200:
            self.owned_ids.discard(drop_id)
            self.owned_ids.add(spare["id"])
            self.team["version"] = resp.json()["version"]

    @task(1)
    def lineup_save_attempt(self):
        """Expected to 422 on today's real data (no verified positions) --
        still a real code path (auth, ownership, roster/season lookups,
        row locks) worth measuring under load, not a broken test."""
        if self.team is None:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        matchdays_resp = self.client.get(
            f"/api/competitions/{COMPETITION_ID}/matchdays", name="/api/competitions/:id/matchdays", headers=headers
        )
        if matchdays_resp.status_code != 200:
            return
        upcoming = [m for m in matchdays_resp.json() if m["status"] == "UPCOMING"]
        if not upcoming:
            return
        starters = list(self.owned_ids)[:7]
        if len(starters) < 7:
            return
        with self.client.put(
            f"/api/teams/{self.team['id']}/lineup?matchday_id={upcoming[0]['id']}",
            json={
                "formation": "THREE_THREE",
                "active_player_ids": starters,
                "captain_id": starters[0],
                "expected_version": self.team["version"],
            },
            headers=headers,
            name="/api/teams/:id/lineup [PUT]",
            catch_response=True,
        ) as resp:
            # 422 (unverified position) is the correct, expected response on
            # today's real data (no position backfill yet) -- a genuine
            # code path worth measuring, not a failure. Anything else
            # (5xx, or a 409 despite this client tracking `version` itself)
            # is a real problem and should still count as a failure.
            if resp.status_code in (200, 422):
                resp.success()


class IdempotencyRetryUser(HttpUser):
    """Smallest share: specifically measures the idempotency-replay path --
    same Idempotency-Key sent twice in a row (simulating a client retrying
    after a perceived timeout), not just fresh-key writes. The second call
    should be a fast replay (200) or a 409 if the first is still in flight,
    never a duplicate transfer."""

    weight = 1
    wait_time = between(3, 6)

    def on_start(self):
        email = f"loadtest-retry-{uuid.uuid4().hex[:12]}@example.com"
        resp = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "loadtest123", "display_name": "Load Test Retry"},
            name="/api/auth/register",
        )
        self.token = resp.json().get("access_token") if resp.status_code == 201 else None
        self.team = None

    @task
    def create_team_with_retry(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.team is None:
            players_resp = self.client.get(
                f"/api/players?competition_id={COMPETITION_ID}", name="/api/players", headers=headers
            )
            if players_resp.status_code != 200:
                return
            players = sorted(players_resp.json(), key=lambda p: p["current_cost"])[:11]
            coaches_resp = self.client.get(
                f"/api/coaches?competition_id={COMPETITION_ID}", name="/api/coaches", headers=headers
            )
            coaches = coaches_resp.json()
            if len(players) < 11 or not coaches:
                return
            self._body = {
                "competition_id": COMPETITION_ID,
                "name": "Retry Test Team",
                "player_ids": [p["id"] for p in players],
                "coach_id": coaches[0]["id"],
            }
            self._key = str(uuid.uuid4())
            resp = self.client.post(
                "/api/teams", json=self._body, headers={**headers, "Idempotency-Key": self._key},
                name="/api/teams [POST first]",
            )
            if resp.status_code == 201:
                self.team = resp.json()
        else:
            # Same key, same body, sent again -- must replay, never 409/duplicate.
            self.client.post(
                "/api/teams", json=self._body, headers={**headers, "Idempotency-Key": self._key},
                name="/api/teams [POST retry-same-key]",
            )
            self.stop()
