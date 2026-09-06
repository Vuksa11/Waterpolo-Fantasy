"""
Baseline load test -- "measure before optimizing" per the performance plan
in docs/FRONTEND_BACKEND_HANDOFF.md. Weighted toward reads (browsing home/
standings/catalog, which is most real traffic for a fantasy app) with a
smaller share of writes (register, create team, transfer).

Run: .venv/bin/locust -f backend/loadtest/locustfile.py --host http://127.0.0.1:8001
Headless example (200 users, spawn 20/s, 60s):
  .venv/bin/locust -f backend/loadtest/locustfile.py --host http://127.0.0.1:8001 \
    --headless -u 200 -r 20 -t 60s --csv=backend/loadtest/results/run1

This is a single dev laptop hitting a single dev Postgres (max_connections=100)
running one uvicorn process -- it measures per-request latency and
correctness under load, not literally "1000 concurrent" (that needs the
multi-worker + PgBouncer deployment from Phase 3 to even be reachable). Real
production-scale validation happens after that deployment exists.
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
    """A smaller share of traffic: new users registering and building a team."""

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

    @task
    def create_team_attempt(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        players_resp = self.client.get(
            f"/api/players?competition_id={COMPETITION_ID}", name="/api/players", headers=headers
        )
        if players_resp.status_code != 200:
            return
        players = sorted(players_resp.json(), key=lambda p: p["current_cost"])[:11]
        if len(players) < 11:
            return
        coaches_resp = self.client.get(
            f"/api/coaches?competition_id={COMPETITION_ID}", name="/api/coaches", headers=headers
        )
        coaches = coaches_resp.json()
        if not coaches:
            return
        self.client.post(
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
        self.stop()  # one team per simulated user, then go idle
