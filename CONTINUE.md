# Continue here

Read this first when resuming. Full architecture/design decisions live in
`docs/Fantasy_Waterpolo_Arhitektura_v2.md` (Section 7 = the authoritative,
continuously-updated Next Steps list) — this file is just the practical
"how do I get back to where I was" pointer, not a duplicate of that doc.

## What this project is

Classic-style fantasy waterpolo. No draft. Covers two real competitions
scraped live from totalwaterpolo.com: **Regionalna liga** (VRL Premier Liga
2025/26) and **VRL Prva Liga** 2025/26. (Super liga Srbije / Prva liga Srbije
were the original target but aren't on the site — scope changed to these two
VRL leagues instead, per the project owner.)

GitHub: `Vuksa11/Waterpolo-Fantasy`, branch `main`. All work so far is
committed and pushed — `git log` is the real changelog, more trustworthy than
prose summaries for what actually happened and when.

## Environment (local dev, not Docker)

This machine runs Postgres natively (installed via apt, not the
docker-compose.yml in this repo, which is unused for now):

- Postgres 16, systemd service, already running as `postgresql.service`.
- DB: `waterpolo_fantasy`, user `waterpolo` / password `waterpolo`.
- Python venv at `.venv/` in this repo root — already has everything in
  `requirements.txt` installed, plus Playwright's Chromium browser
  (`playwright install chromium` — no `--with-deps` needed, works fine
  without extra system libs on this machine).
- `.env` at repo root has `DATABASE_URL` (asyncpg, for the backend) and
  `DATABASE_URL_SYNC` (psycopg2, for the scraper/alembic).

**Running the API locally** needs both the repo root and `backend/` on
`PYTHONPATH` (`db/` and `scoring/` are top-level packages the backend imports,
but `app/` lives under `backend/`):

```
PYTHONPATH=$(pwd):$(pwd)/backend DATABASE_URL=postgresql+asyncpg://waterpolo:waterpolo@localhost:5432/waterpolo_fantasy \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --app-dir backend
```

(Port 8001, not 8000 — see Codex section below for why.)

**Running the scraper pipeline** (idempotent — safe to re-run, only touches
matches that don't have player_stats yet):

```
DATABASE_URL_SYNC=postgresql+psycopg2://waterpolo:waterpolo@localhost:5432/waterpolo_fantasy \
  .venv/bin/python -m scraper.run
```

**Migrations**: `cd backend && ../.venv/bin/python -m alembic upgrade head`.
Current head: `11873788c5dc` (9 migrations total, see
`backend/alembic/versions/` -- includes the merge revision joining the
`main`/`frontend` branch alembic chains, see the merge section below).

**Running tests**: `.venv/bin/python -m pytest` from the repo root (no manual
`PYTHONPATH`/`DATABASE_URL` needed -- `pytest.ini` sets `pythonpath`, and
`.env` already has `DATABASE_URL`). Tests run against the real local dev
Postgres DB (this project has no sqlite/mock-DB layer), create their own rows
and clean them up after. `backend/tests/test_idempotency.py` is the only
suite on `main` so far -- Codex's `frontend` branch has its own, broader
suite (`backend/tests/test_teams.py` etc., using an in-memory sqlite adapter)
that should be reconciled/merged in once branches combine, not duplicated.

## Another AI (Codex) is building the frontend — read this before touching backend/app

The user set up a second AI session (Codex) building the frontend in a
**separate git worktree**: `/home/vuksa/Pictures/Desktop/FantasyWP-frontend`,
branch `frontend`, its own isolated Postgres on port 55432. Coordination
happens through **`docs/FRONTEND_BACKEND_HANDOFF.md`** — read it in full
before making backend API changes; it has the live contract (endpoint
shapes, who owns what, open questions each side asked the other) and is more
current than anything in this file. Append to it (don't just read) when you
change something Codex's frontend depends on.

Codex's frontend dev server runs on `:3000` with `API_TARGET=http://127.0.0.1:8001`
— that's why the backend needs to run on **8001**, not the default 8000, when
checking on their work. Their dev server may already be running (check
`ss -ltnp | grep 3000` before starting your own — don't kill their process).
Check in on `FantasyWP-frontend` periodically (read-only unless asked
otherwise) and actually run it (Playwright screenshot or similar) rather than
just reading source, per how the last check-in found a real missing endpoint
(`/api/coaches`) that a pure code read hadn't caught.

## Current status (as of commit `054cd73`)

Verified against the real database (352 players, 132 matches, all live-
scraped, not synthetic):

- **Scraper**: fully working (`scraper/`) — schedule + box-score parsing via
  headless Playwright rendering (the site's data loads client-side against a
  token-gated API; rendering the real page sidesteps that legitimately).
- **Scoring** (`scoring/engine.py`) and **price changes** (`scoring/price.py`):
  implemented and verified against the full dataset.
- **API** (`backend/app/routers/`): read-only sports data (competitions,
  standings, players incl. catalog/facets, matches, matchdays) + auth
  (email/password, JWT) + fantasy team creation/transfers (budget-checked,
  transactional). All live-tested, including via Codex's own test suite,
  which caught and got fixed: a password-hashing crash over 72 bytes, a SQL
  LIKE-escaping bug in player search, and missing limit/offset/sort
  validation.
- **NOT built yet**: lineup management (formation, bench, captain,
  per-matchday scoring for a team) — blocked on `players.position`, see
  below. Codex has already designed and tested (against synthetic data) the
  API shape for this — `PUT /api/teams/{id}/lineup`, optimistic concurrency
  via a `version` field, deadline-based locking — worth adopting rather than
  re-designing when this gets built.
- **Performance/scale plan** (target: ~1000 concurrent of ~10k total
  registered users, "instant"-feeling pages) — a joint plan negotiated with
  Codex via the handoff doc, Phase 1 done: DB pool tuning (unmeasured
  default guess, not a proven fix — a real load test is still owed before
  claiming the target is met), fixed an N+1 roster query, added indexes on
  every FK/lookup column actually queried (18 total, `CONCURRENTLY`), gzip +
  `Cache-Control` (public on read-only sports data, explicit `private,
  no-store` on auth/teams), a `GET /api/home` bundle endpoint (avoids a
  4-5-request waterfall on the landing page, exact contract negotiated with
  Codex), and `Idempotency-Key` support on team creation/transfers (a client
  retry after a timeout replays the original response instead of risking a
  duplicate). Redis caching and the actual load test (k6/locust) are next,
  by mutual agreement, only once there's something to measure against.
- **Three rounds of independently-verified findings from Codex's review** (the
  frontend session periodically reviews main's code and posts findings to
  the handoff doc as `Problems/problemV*.md` on the shared Desktop -- read
  those + the doc's tail before assuming "done"): (1) an idempotency
  implementation that wasn't atomic with the operation it guarded and had a
  real race under concurrent identical requests -- rewrote as a two-phase
  claim/fulfill/release pattern, verified with an actual two-thread
  concurrent test (not just sequential calls); a Cache-Control middleware
  bug that skipped private-prefix checking for every non-GET method,
  silently leaving POST /api/auth and POST /api/teams uncached-but-also-
  unmarked; and a home-bundle endpoint that could mix matchday/standings
  across seasons. (2) The first real load test (locust, 100 concurrent,
  backend/loadtest/) caught bcrypt blocking the whole event loop on
  register/login -- fixed with asyncio.to_thread, aggregate p95 dropped
  310ms -> 54ms. (3) problemV9: `current_user.id` read after `db.rollback()`
  in `create_team`/`make_transfer`'s exception handlers -- confirmed by
  *directly reproducing* the underlying SQLAlchemy behavior (a rollback'd
  ORM row's `.id` access raises `MissingGreenlet` in async mode), which
  would've turned an intended 4xx into an unhandled 500 and skipped
  releasing the idempotency claim; plus a claim-retry gap (a vanished
  conflicting row was treated as "already claimed" with no placeholder
  actually inserted) and an `except HTTPException`-only catch that left
  idempotency claims stuck at "pending" forever on any other exception.
  Fixed: both routes now capture `user_id = current_user.id` before any DB
  work and never touch `current_user.id` again afterward, `_claim_idempotency_key`
  retries the claim (up to 3x) when the conflicting row vanishes, and both
  handlers now catch `except Exception`. Re-verified: normal transfer still
  works, an invalid transfer with an Idempotency-Key now returns a clean 404
  (not 500) with the claim actually released (checked via direct DB query,
  not just the HTTP response), and the two-thread concurrent race test still
  shows the same correct 409/200/clean-replay behavior with no duplicate
  transfer rows. Every finding across all three rounds was re-verified by
  reading the exact cited code (or reproducing it directly) before fixing,
  not accepted on trust -- worth continuing that habit, Codex's reviews have
  had a 100% hit rate on real bugs so far. (4) problemV10: caught that my
  problemV9 fix's `except Exception` doesn't catch `asyncio.CancelledError`
  (a `BaseException` subclass since Python 3.8, confirmed independently) --
  a cancelled request task (client disconnect, server shutdown) mid-transfer
  still left the idempotency claim stuck at "pending" forever. Also correctly
  called out that my prior "all three P1s fixed" framing was overstated when
  the third was only partially closed. Fixed: both handlers now catch
  `except (Exception, asyncio.CancelledError)`, re-verified deterministically
  (mocked fault injection, same technique Codex used) that `release()` now
  runs and `CancelledError` still propagates correctly. Also added real
  persisted regression tests (`backend/tests/test_idempotency.py`, run via
  plain `pytest` from repo root thanks to the new `pytest.ini`) per Codex's
  point that manual/scratch-script checks aren't a substitute -- covers the
  normal-transfer, invalid-transfer-releases-claim, concurrent-race, and
  cancellation scenarios. Process-crash recovery (kill -9) remains an
  explicitly open gap, not solved by this or any exception handler. (5)
  problemV11: reviewed the new tests themselves and found two real P2s --
  `test_concurrent_same_key_transfer_serializes` asserted an exact
  [200,409] split, which assumes a specific scheduling outcome between two
  genuine concurrent asyncpg round-trips rather than a guaranteed one
  ([200,200] is equally valid if the loser's re-check lands after the
  winner already fulfilled); and `roster_fixture` picked "the first
  competition" without checking its cheapest roster actually fits the
  100-credit budget. Both confirmed by reasoning through the actual code
  paths before fixing. Fixed: the concurrent test now accepts either
  status split and checks the real invariant instead (byte-identical
  replay bodies, exact SELL/BUY entity+price in the DB, correct
  credit_balance math, unchanged history count after a retry);
  `roster_fixture` now scans every competition for one with an affordable
  full roster instead of assuming the first one works. All 4 tests still
  pass repeatably. Also flagged (correctly, no code change needed) that
  cancellation exactly during the idempotency claim's own commit -- before
  the caller's try block even starts -- is the same class of unrecoverable
  gap as a process crash, not a new one; the same background sweep/lease
  fix already tracked as open would cover both.

## Phase 1 status (performance/scale plan)

Phase 1 (docs/FRONTEND_BACKEND_HANDOFF.md: N+1 fix, pool tuning, indexes,
gzip, Cache-Control/ETag) is now functionally complete -- ETag was the one
item from the original list never actually implemented; added it in commit
`47d1e4e` (`CacheControlMiddleware` now hashes the response body for cacheable
GETs, supports `If-None-Match` -> 304, verified live and in
`backend/tests/test_caching.py`). The remaining Phase-1-adjacent item
(reconciling the alembic migration branch with Codex's `c83207f2a491`/
`d93418e3b502` chain) can't be finished in isolation -- it's tied to the git
merge itself (see below). Idempotency crash-recovery (background sweep/lease)
was never part of the original Phase-1 list; it's a separate open item from
the V9-V12 review rounds, still unresolved.

## Merge with the `frontend` branch is DONE (2026-09-06, commit `5a823d5`)

The user asked to get this moving, then said not to wait hours for Codex's
reply and to go ahead. Real starting state: `frontend` had merged `main` at
commit `85c5109` -- 18 of my commits behind (before the whole performance
plan, `/api/home`, the idempotency-key mechanism, every problemV8-V13 fix,
ETag, the test suite). Codex independently built `version`/deadline/
ownership/lineup management on that old `teams.py` in the meantime, while I
independently built idempotency claim/fulfill/release on mine.

Did the merge on a throwaway branch (`merge-frontend-attempt`) first,
verified everything, THEN fast-forwarded `main` onto it -- nothing went
straight to `main` unverified. Key decisions:

- `teams.py`/`schemas.py`: frontend's write-model is the base (Decimal
  `money()`, `check_window`/`current_window` deadline gating, `owned_team`,
  batched `team_outputs`, `save_lineup`/`get_lineup`, the richer
  `TeamOut`/`RosterEntryOut`/`TeamCreateIn`). My idempotency claim/fulfill/
  release wraps `create_team` and `transfer`, unchanged otherwise.
  `MatchdayOut` keeps both frontend's `deadline` field and my
  `_MatchdayDisplayLabelMixin`.
- **Self-caught mistake, fixed before it shipped**: first pass deliberately
  dropped `current_window` from `transfer()`, reasoning it would 409 every
  transfer against today's historical/no-deadline data. Running frontend's
  own `test_teams.py::test_closed_windows_and_unknown_positions` caught this
  as a real failure -- correctly: a real fantasy transfer must never skip
  deadline gating just because current data has no upcoming gameweek.
  Reverted to match frontend's tested behavior exactly.
- Alembic: real merge revision `11873788c5dc` joins frontend's
  `c83207f2a491`->`d93418e3b502` chain with mine
  (`e2f53c959c38`->`d86291b3557f`) at their shared parent `f2806bcaae2f`.
  Applied to the dev DB -- `fantasy_teams.version` and `lineups` now coexist
  with `idempotency_keys` and every index from both sides.
- Git's silent (no-conflict-marker) auto-merges were NOT trusted blindly --
  diffed `players.py`/`db/models.py`/`core/config.py`/`matchdays.py` against
  both original branches by hand. One looked like a regression at first
  (players.py's SQL-escape/422-validation) but turned out to be a restyle
  with identical protection (inline escape, `Literal`/enum FastAPI types
  instead of manual checks) -- confirmed before concluding either way.

Verified: full suite (16 tests -- 10 frontend's + 6 mine) passes repeatably
(3x in a row), dev DB clean each time. Also exercised the live server
end-to-end outside pytest (register -> create team -> transfer 409s with no
upcoming matchday -> 200 once a test-only UPCOMING+future-deadline matchday
exists -> save_lineup 422s cleanly on unverified positions) and the live
frontend on :3000 against this backend (no console errors, no 4xx/5xx,
banner correctly shows "Finale" via Codex's own independent fix).

Pushed to `origin/main` (`5a823d5`). Posted a full writeup in the handoff
doc. Codex's `frontend` branch is untouched -- when they're ready to
rebase/merge it onto the new `main`, most of the hard conflicts are already
resolved here, so it should be much thinner. Also separately pushed an
unpushed local commit (`bad666f`) from the `frontend` worktree that the user
noticed Codex hadn't pushed.

Known follow-ups NOT resolved by this merge (unchanged from before):
idempotency crash/cancellation-during-claim recovery (background sweep/lease
needed), `(user_id, league_id)` uniqueness for create_team's distinct-request
race, auth email uniqueness race, per-competition `scrape_runs` freshness,
real position/deadline data (blocked on the project owner), and the actual
1000-concurrent load test (Phase 3, not started).

## Load test with the write profile (2026-09-06, commit `76894ab`)

User said not to wait for Codex (unavailable until ~noon) and to keep going
with the agreed plan -- "measure before Redis" per the performance plan, now
that the merge is done. Extended `backend/loadtest/locustfile.py` with the
transfer/lineup/idempotency-retry coverage Codex's V10/V12/V14 reviews had
correctly flagged as missing (only `create_team` was covered before). Added
`backend/loadtest/prepare_upcoming_matchday.py` -- needed because every real
matchday in the dev DB is a finished historical round with no deadline, so
transfer()/save_lineup() would 409 instantly without a test-only
UPCOMING+future-deadline matchday, which would measure nothing useful about
write-lock behavior under load.

**100 concurrent, 90s, full write profile**: 0% failures across 3761
requests, aggregate p95 30ms, p99 57ms.

**300 concurrent, 90s, full write profile**: still 0% failures, but latency
degrades a lot -- aggregate p95 250ms, p99 920ms, `POST /api/teams` p98
~2700ms. Tried 4 uvicorn workers (with `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`
turned down to 10/10 each to stay under Postgres's `max_connections=100`) --
didn't meaningfully help, which is itself informative.

**Isolated the cause**: re-ran the same 300-concurrent test with ONLY
`BrowsingUser` (no writes at all) -- aggregate p95 drops to **37ms**, p99 to
**67ms**, still 0% failures. So the read-heavy majority of real traffic
already scales fine today, no Redis needed for that. The degradation comes
specifically from `create_team`'s `Season...with_for_update()` row lock,
held across the ENTIRE handler (league lookup/create, roster insert,
idempotency fulfill, commit) -- every concurrent create_team call for the
SAME season effectively serializes behind it. More workers didn't help
because the bottleneck is DB row-lock contention, not CPU/process capacity.

Did NOT touch `create_team`'s locking logic -- it's the frontend branch's
business decision (presumably deliberate, to prevent a duplicate "Globalna
liga" row under concurrency), and create_team is a rare once-per-user event,
not something that affects typical browsing. Proposed in the handoff doc (not
implemented): a partial unique index on `leagues(season_id) WHERE admin_id IS
NULL` could give the same duplicate-prevention guarantee without holding a
lock across the whole handler -- catch the IntegrityError and re-read,
similar to the idempotency claim pattern. Left as an open discussion point,
not an unrequested rewrite of their code.

**Then pushed to the actual target -- 1000 concurrent, read-only, 1
worker**: this is where the real ceiling shows up. Aggregate p95 jumps to
**8000ms**, p99 to **13000ms**, max 30000ms, and two real `500`s appear --
confirmed in the log, not guessed: `sqlalchemy.exc.TimeoutError: QueuePool
limit of size 20 overflow 20 reached, connection timed out, timeout 30.00`.
The single process's 40-connection DB pool saturates completely under 1000
concurrent requests; the rest queue and some time out after 30s.

**Tried the same with 4 uvicorn workers** (`DB_POOL_SIZE=15`/
`DB_MAX_OVERFLOW=5` each, 80 total, under Postgres's `max_connections=100`):
**0% failures**, throughput 210->358 req/s, p95 8000ms->**1600ms**, p99
13000ms->**2300ms**, max 30000ms->4500ms. A big improvement, and proof Phase
3 (more workers) actually matters at this load level -- unlike the write
contention above, more workers/more DB connections directly help here since
there's no row-lock serialization involved.

**Revising my earlier conclusion** (from the 300-concurrent result) that
Redis wasn't needed -- that was true AT 300 concurrent, but not sufficient
for the actual ~1000-concurrent target: even with 4 workers, p95=1.6s/
p99=2.3s at 1000 users isn't an "instant" feel. Redis (Phase 2) would likely
help here precisely by cutting the number of queries that have to wait on
the DB pool at all -- standings/catalog/home change rarely (only after a
scraper run), so a short-TTL cache is safe there, freeing pool capacity for
whatever actually needs to hit the DB.

**Conclusion (revised)**: up to 300 concurrent, reads already scale fine
with nothing extra. For the actual ~1000-concurrent target, BOTH Phase 3
(more workers -- proven to help significantly) AND Phase 2 (Redis -- not
implemented yet, but the finding above is the first concrete evidence it's
actually needed, not just nice-to-have) are required. `create_team` write
contention stays open for discussion. Raw CSVs (including the 1000-
concurrent runs, 1 and 4 workers) in `backend/loadtest/results/`. Server
reverted to normal single-worker mode after measuring.

## Phase 2 (Redis cache) implemented, blocked only on installing the server

Went straight from finding "Redis would likely help" to building it, same
session. `redis-server` itself isn't installed (needs `sudo`, see "Blocked
on the user" below) so the real 1000-concurrent perf win can't be measured
live yet -- but the application-side code is done, tested, and safe to ship
as-is (it's inert until `REDIS_URL` is set).

- `app/core/config.py`: `redis_url: str | None = None` (unset = cache
  disabled, zero behavior change) and `redis_cache_ttl_seconds: int = 30`
  (matches the existing Cache-Control window -- one staleness budget to
  reason about, not two).
- `app/core/cache.py`: `get_or_compute_json(key, compute, ttl)` -- the one
  function routes call. Every failure mode (Redis absent, Redis
  unreachable, a GET/SET erroring mid-request) degrades to "run compute()
  against Postgres like before this existed", logged as a warning, never
  raised to the caller. A Redis outage in production must never take the
  API down with it.
- Wired into the four routes the load test showed matter most: `/api/home`,
  `/api/competitions/{id}/standings`, `/api/players/catalog` (keyed on
  every filter/sort/page combination), `/api/players/facets`. Each route's
  DB logic moved into a `_compute_*` helper returning a plain JSON-safe
  dict; the route function does cache lookup -> `_compute_*` on a miss ->
  parses the (possibly cached) dict back into its real Pydantic response
  model, so `response_model` validation is unaffected either way.
- Tested three ways: (1) full pytest suite (20 tests, including the
  existing 16) passes with NO `REDIS_URL` set -- confirms zero behavior
  change when the cache is off, which is the default; (2) new
  `backend/tests/test_cache.py` (4 tests) uses `fakeredis` (real Redis wire
  protocol, in-memory, no server needed) to prove the cache actually works,
  not just that it degrades gracefully -- a real cache hit skips
  `compute()` entirely, different keys don't collide, TTL expiry forces a
  real recompute, and a simulated mid-request Redis error still returns the
  correct value; (3) manually ran the live server with `REDIS_URL` pointing
  at a port nothing is listening on -- every request still returned 200,
  the connection error was logged as a warning, confirmed live, not just
  in a test.
- `redis`/`fakeredis` added to `requirements.txt`, pinned to what's
  actually installed (8.1.0 / 2.37.1).

Next when `redis-server` exists: set `REDIS_URL=redis://localhost:6379` in
`.env`, restart, then re-run the 1000-concurrent read-only load test
(`backend/loadtest/locustfile.py BrowsingUser`) to see whether it actually
closes the gap between the 4-worker result (p95 1600ms) and something
closer to "instant" -- that comparison is the real point of building this,
not just having Redis wired up unmeasured.

## Redis measured live -- the target is met (same session, right after)

User installed `redis-server` (now a running systemd service) and said to
continue. Set `REDIS_URL=redis://localhost:6379` in `.env` (permanent, not
just this session's env var), restarted, confirmed live with `redis-cli
keys "*"` that cache entries actually appear after a real request (not just
theoretically wired up). Full pytest suite (20/20) still passes with Redis
live.

**1000 concurrent, read-only, 1 worker + Redis** (vs. the same test without
Redis from the previous section): aggregate p95 **8000ms -> 55ms**, p99
**13000ms -> 110ms**, throughput 210 -> **~450-499 req/s**, 0% failures (no
more QueuePool timeouts). This IS an instant feel at the actual target load
level.

**Surprising, honestly-reported finding: 4 workers + Redis is slightly
WORSE than 1 worker + Redis** (p95 170ms, p99 390ms -- still excellent, but
worse than one process). Explanation: Redis already eliminated the DB pool
saturation that was the ONLY reason more workers helped earlier; with that
bottleneck gone, extra processes on this 4-core machine just add CPU
context-switching overhead with no offsetting benefit. On this machine, the
best configuration is 1 worker + Redis, not 4 workers + Redis -- worth
noting for a real deployment: worker count should be tuned against the
ACTUAL bottleneck, not assumed "more is always better."

**Full write profile (transfer/lineup/registration), 300 concurrent, 1
worker + Redis**: also substantially better than without Redis -- aggregate
p95 250ms->**43ms**, p99 920ms->**270ms**. `POST /api/teams` still shows
higher variance (p98 890ms) -- that's still create_team's Season row-lock
contention, which Redis doesn't fix directly (the write path isn't cached),
only indirectly helps by freeing DB pool capacity.

**Conclusion (final for this round)**: the ~1000-concurrent target with an
"instant" feel is achieved for read-heavy traffic (the vast majority of
real traffic) -- Redis + 1 worker gives p95=55ms/p99=110ms at 1000
concurrent reads. `create_team` write-lock contention remains the one open
discussion item (partial unique index proposal already in the handoff doc).
Raw CSVs (1000-concurrent with/without Redis, 1 and 4 workers; 300-
concurrent write profile with Redis) in `backend/loadtest/results/`. Server
left running with `REDIS_URL` set, 1 worker (`.env` updated permanently, not
just for this session).

## `players.position` and real coach names — RESOLVED (2026-09-07)

No longer blocked. The user manually annotated `players.position` for
almost every scraped player (reference file `~/Downloads/rosteri2.0.txt`,
17 clubs, 352 players) and supplied real coach names for 7 clubs. Applied
to the DB:

- **348 of 352 players now have a real `position`** (`GK`/`OT`/`CF`/`CB`).
  4 remain `NULL`, intentionally, because there is no reliable way to
  resolve them: 2 are the known unnamed-goalkeeper placeholder rows (name
  `"- -"`, Primorac and Šabac Elixir — pre-existing, documented issue, see
  the goalkeeper-stable-ID note below), and 2 (`Samuil Tsvetanov Ivanov` at
  Radnički, `Nemanja Ilić` at Nais Niš) were left without a position
  annotation by the user in the source file — not guessed, flagged instead.
  **Superseded below** (see "problemV17.md" section further down): 18 more
  players lost their position after a duplicate-identity correction, and
  the whole thing was rewritten as a committed, reproducible script — 330,
  not 348, is the current real count.
- **Cattaro** (23 players) had zero position annotations in the source
  file. Per the user's explicit instruction, positions were assigned by
  hand to mirror the position mix of the other 16 clubs (roughly OT 57%,
  GK 16%, CB 16%, CF 10%): GK=3, OT=13, CB=4, CF=3. This is **not**
  researched/real data — it's a deliberate placeholder assignment, done
  only because the user asked for one; worth revisiting if a real Cattaro
  roster/position source ever turns up.
- **Duplicate same-name rows**: several clubs have two distinct `Player`
  rows sharing one name (e.g. two "Matija Vlahovic" rows at Crvena Zvezda).
  In every case but Cattaro's, the user's file gave a position to exactly
  one occurrence and left the other blank — both DB rows were set to that
  same position, since there's no way to tell which physical row is which.
- **Coach names**: 13 of 17 clubs now have a real `Coach.name` (round 1: 8,
  round 2 same day added 5 more after the user asked for a deeper, more
  thorough search). 7 came straight from the user's file (NBG Tehnomanija:
  Zoran Bajić, Partizan: Stefan Ćirić, Radnički: Uroš Stevanović, Šabac
  Elixir: Nemanja Ličanin, Beograd: Nikola Milosavljević, NBG Vukovi: Nenad
  Vasilovski, Valis Vega: Miloš Saković). The other 6 came from web
  research, each cross-checked before being trusted:
  - **Jadran m:tel HN → Petar Radanović** — pvkjadran.com's official squad
    page; 7 of 15 scraped roster names (Danilo Stupar, Dmitri Kholod, Ilija
    Radovic, Jovan Vujovic, Matija Sladovic, Strahinja Gojkovic, Vasilije
    Radovic) match exactly.
  - **Budućnost One → Aleksandar Aleksić** — pvkbuducnost.me's coverage of
    "PVK Budućnost" (Podgorica); 13 of 22 scraped roster names matched its
    published squad — the strongest cross-check of this whole round.
  - **Primorac → Anastasios (Sakis) Kehajas** — reported by 4 independent
    Montenegrin outlets (RTCG, CDM, aktuelno.me, gradski.me), appointed 24
    June 2025, replacing Vjekoslav Pasković. No roster to cross-check, but
    corroborated by multiple outlets with a specific date.
  - **Budva BDR → Miloš Popović** — December 2025 Cup-of-Montenegro final
    four coverage that also named Primorac, Budućnost One, and Jadran m:tel
    as the other 3 semifinalists — exactly our own club list, strong
    contextual confirmation.
  - **Vojvodina → Darko Bilić** — consistent across multiple 2025 sources
    (uvts.rs coach registry, vaterpolovesti.com, a September 2025 tournament
    mention).
  - **Zemun → Andrija Vasiljević** — official club site (vkzemun.org.rs),
    both its "Stručni štab" and "Prvi tim 2025-2026" pages; cross-checked
    via player "Milan Bulajić" appearing on both the official roster and our
    own scraped one. **Side note surfaced by this check, not acted on**: the
    official site lists Aleksa Damjanović at jersey #13 (a GK number), while
    the user's file marked him "OT" — flagged, not silently overridden,
    since the user's manual position annotation was treated as the source of
    truth this round.
  Still had no verifiable real name after a genuinely thorough search:
  - **Crvena Zvezda** — actively coachless per multiple 2026 news reports:
    coach Aleksandar Filipović left mid-season (too few players showing up
    to training), separate reports describe the club in serious financial
    trouble. There's no stable coach to name right now.
  - **Cattaro (VA Cattaro)** — a "new season" presentation names 4 people
    (Mlađan Tujković, Željko Vičević, Nebojša Milić, Ivan Bjelobrković) with
    no indication which one is the sole head coach — reads as a multi-coach
    academy staff, not a single-name role.
  - **Nais Niš** — every source found (several search phrasings tried) was
    stale (2015–2018) or silent on 2025/26.
  - **Stari Grad** — confirmed former coach Zoran Mijalkovski left for Novi
    Beograd (Feb 2026, total-waterpolo.com's own news post), but no
    successor was found anywhere.

  Per the user's explicit follow-up request ("za preostale trenere uradi
  mock za sad"), these 4 now carry a **fictional placeholder name, suffixed
  `(mock)`** instead of the old "— trener TBD" text: Crvena Zvezda → Dušan
  Marković (mock), Cattaro → Ivan Radulović (mock), Nais Niš → Vladimir
  Antić (mock), Stari Grad → Dejan Simić (mock). These are made up, not
  sourced from anything — swap them out the moment a real name is found or
  supplied.
- Investigated the two "- -" unresolved-name player rows (Primorac,
  Šabac Elixir) at the user's request, since the working assumption in this
  doc and in `player_resolver.py`'s docstring was that these were
  goalkeepers without a stable id. **That assumption was wrong for these two
  specific rows** — rendered the actual match pages via the existing
  Playwright scraper (`fetch_boxscore.render_match_page`, matches 12534 and
  12536) and found both are jersey **#16 FIELD players** (not goalkeepers,
  `#homePlayers`/`#awayPlayers` section, not `#...Goalkeepers`), each with a
  perfectly stable `external_player_id` (11670 and 4603) from a normal
  `OpenPlayerPage(...)` onclick. Also loaded each player's own profile page
  on the source site (`total-waterpolo.com/tw_player/11670` and `/4603`) —
  both show the name field itself as literally "- -", with every other bio
  field (position/hand/height/weight) blank too, and both play in
  youth-adjacent competitions (U-15 Montenegro Cup, etc.) alongside VRL
  Premier. **Conclusion: this is a real data gap on totalwaterpolo.com
  itself** (the site never published these two young players' names), not a
  scraper bug and not something further searching can fix — left as `NULL`
  name is already correct behavior, no code or data change needed.
  Follow-up check the user asked for specifically: Šabac Elixir's actual
  goalkeepers (jersey #1 "Darko Djurovic", jersey #13 "Veljko Tomić", both
  visible in the same match's `#homeGoalkeepers` section) are **not**
  missing — both already exist in the DB with the right name and `GK`
  position. The "- -" row is a separate, unrelated player (jersey #16,
  regular field-player section) — the goalkeepers were never the ones with
  the gap. Also
  checked whether total-waterpolo.com exposes coach data anywhere (a
  `tw_team/{id}` profile page pattern exists and was tried for several
  clubs) — confirmed it does not; the whole "coach names" search had to be
  general web research for this reason.
- Full test suite re-run after applying: 42 passed, 0 failed.
- `save_lineup`'s formation validation and the frontend team-builder's
  "Nedostaje potvrđena pozicija" disabled state now have real position data
  to check against for most players. **Correction (an independent review,
  Codex, problemV17, correctly pushed back on this):** this is not the same
  as "the real team-builder flow is unblocked end-to-end" -- confirmed live
  that both competitions currently have 0 matchdays with status UPCOMING,
  and `check_window` in `app/routers/teams.py` correctly rejects any
  lineup/transfer without one, regardless of position data. Position data
  existing removes one blocker, not the only one; an actual end-to-end
  check needs a fixture with a real future deadline, not the historical
  matchdays currently in this dataset.

- **Goalkeeper stable IDs** — field players get a stable external id
  straight from the box score; goalkeepers don't (confirmed, not a bug).
  Needs a team-squad page sample to resolve properly; currently matched by
  (name, club) instead. Not blocking anything today, just less robust.

## Independent review by "Fable" (separate session, 2026-09-06)

The user ran a second, independent AI session (Fable model) specifically to
evaluate the work so far -- not part of the Claude<->Codex collaboration,
no prior involvement in writing any of this code. Full report saved at
`docs/NEZAVISNA_OCENA_KODA.md` (Serbian). Overall verdict: 6.5/10 -- code
quality/transactional correctness scored 8.5/10 ("surprisingly mature"),
but fantasy-product completeness scored 3/10 because the actual scoring
loop doesn't exist yet, and production-readiness outside features scored
4/10. Findings independently verified live (ran the test suite, hit
running endpoints with SQLi/XSS/oversized-password/brute-force attempts,
read the code directly) -- this isn't a docs-only review.

**Confirmed independently before acting on it** (same discipline used for
every Codex review round): grepped the codebase myself and confirmed
`fantasy_teams.total_points` is read but genuinely never written anywhere.

Critical findings (blocking "real fantasy product," not code-quality bugs):
1. **No team-level scoring aggregation** -- `scoring/engine.py` computes
   per-player `raw_points` correctly, but nothing sums a saved lineup's
   active-player scores (with captain x2 / bench x0.5 multipliers) into
   `fantasy_teams.total_points` after a matchday. This is the single
   biggest gap -- already correctly flagged as "not yet built" in
   `docs/Fantasy_Waterpolo_Arhitektura_v2.md` Section 7 item 8, but worth
   naming explicitly: auth/teams/transfers/idempotency/pricing all work:
   scoring itself is the one missing piece of the actual game loop.
2. **No fantasy leaderboard** -- FIXED same session, see the commit above
   (`GET /api/competitions/{id}/leaderboard`, correct in shape today, will
   show real numbers once #1 is built).
3. **`players.position` still null for every player** -- RESOLVED
   2026-09-07, see "`players.position` and real coach names — RESOLVED"
   above: 348/352 players now have a real position, unblocking
   `save_lineup`'s formation validation for almost the entire dataset.
4. **No rate limiting / brute-force protection on auth** -- confirmed live:
   15 consecutive wrong-password attempts against the same account all
   returned a clean 401, no 429, no lockout, no CAPTCHA. bcrypt's own cost
   is the only friction (~240ms/attempt), which slows but doesn't stop a
   distributed or patient attacker. Not yet fixed.
5. **No email verification or password reset.** Not yet fixed.
6. **No logging/observability/monitoring** -- no Sentry/structlog/
   Prometheus, errors only ever go to the process's own stdout traceback.
   Particularly relevant since the scraper (an external dependency on a
   third-party site) can silently break with nothing raising an alert.
   Not yet fixed.
7. **No CI/CD pipeline** -- test suite exists and is good, but nothing runs
   it automatically on push. Not yet fixed.

Minor findings (not blocking, worth tracking): no CORS middleware (fine
today since the frontend proxies same-origin, would matter for any second
client e.g. the planned mobile app); `/docs` (Swagger UI) publicly exposed
with no protection; `scrape_runs` not scoped per competition (already
known); idempotency crash-recovery still open (already known, tracked
since problemV9); no `(user_id, league_id)` unique constraint on
`fantasy_teams` (already known, tracked since problemV8); `datetime.utcnow()`
deprecation warnings (cosmetic); no admin/moderation layer; the
architecture doc (Section 2.1) still lists "one wildcard per season" as
in-scope even though it was deliberately never implemented once the
transfer limit it depended on was removed -- worth reconciling the doc.

Legal status of scraping totalwaterpolo.com was explicitly excluded from
this review's scope (the project owner's call, not a technical question).

## Items 4-5 done (rate limiting, email verification/password reset) +
## 6 real bugs Codex found and fixed, same session (commit 9276c07)

User picked items 4-7 from Fable's list to do next. Built rate limiting
(app/core/ratelimit.py: per-IP throttle + per-email login lockout,
directly closing the exact gap Fable demonstrated) and email
verification/password reset (app/core/email.py logs the link instead of
sending -- no real SMTP/provider configured; login NOT gated on
verification for that reason, documented).

While that was still uncommitted work-in-progress, Codex's problemV15
review caught it on disk and found a real bug: the rate limiter's
INCR-then-separate-EXPIRE could leave a key with NO ttl if the process
died between the two -- reproduced independently with fakeredis before
fixing (TTL stuck at -1, permanently over its limit). Fixed with an
atomic `SET NX EX` plus a self-heal check for already-damaged keys.

Codex also re-reviewed already-committed code (the Redis/leaderboard
work from the previous two sections) and found three more real bugs,
all independently reproduced before fixing:
- Cache key collision: `f"{search}:{club}"` let DIFFERENT filters
  produce the SAME key (search="a:None:b",club="c" collided with
  search="a",club="b:None:c") -- one user's search could get served
  another's cached results. Fixed with a JSON-encode+hash key builder
  (`make_cache_key`), applied everywhere, key version bumped.
- An invalid REDIS_URL raised synchronously OUTSIDE any try/except,
  propagating out of every cache call instead of degrading to "no
  cache" like every other failure mode. Fixed.
- 25 concurrent cache misses for the same key ran the DB query 25
  times (no in-flight deduplication). Fixed with a per-key
  `asyncio.Lock` (single-process only, documented).

Also confirmed and fixed: `request.client.host` alone doesn't identify
the real browser user once `frontend/server.mjs` proxies requests (it
doesn't set `X-Forwarded-For` today, confirmed by reading it -- every
user through it currently shares one rate-limit bucket). Added a
trusted-proxy-only `get_client_ip()` (doesn't trust that header from an
untrusted source) and proposed a one-line `server.mjs` change to Codex
in the handoff doc (not implemented there -- their file). And corrected
a stale comment in `create_team`: the merged handler's Season row lock
already serializes concurrent calls for the same season, closing the
race the old comment described as still open (documented what must be
preserved -- a unique constraint -- if that lock is ever narrowed).

42 tests now (was 31), passes repeatably (3x) with and without
REDIS_URL, dev DB clean after every run. Full response posted to Codex
in the handoff doc.

## Items 6-7 done (structured logging, CI) -- all of Fable's items 4-7 closed

Same session, straight after. Item #6: `backend/app/core/logging_config.py`
gives every logger in the codebase an actual handler (previously none did --
confirmed live that `app.core.email`'s logger.info() calls, the only
visibility into the email-verification/reset links, were completely
silent). Added `RequestLoggingMiddleware` (method/path/status/duration per
request, WARNING on 5xx) and switched `scraper/run.py` from `print()` to
`logging` (ERROR level when a run had failures) -- directly addresses
Fable's point that the scraper is the platform's only connection to "the
truth" about a match and could silently break.

Item #7: `.github/workflows/backend-tests.yml` -- Postgres 16 + Redis 7
service containers, installs requirements.txt, runs Alembic migrations,
runs the full pytest suite, on every push/PR to main. Couldn't dry-run this
locally (no CREATEDB privilege on the dev Postgres role, sudo unavailable
in this environment) -- pushed it and watched the actual first run instead
(`gh run watch`), which is the real validation, not a local approximation:
**36 passed, 6 skipped, 0 failed** in 57s. The 6 skips are exactly the
tests that need real scraped data (test_idempotency.py,
test_leaderboard.py's team-creation tests) against this CI DB (freshly
migrated, no scraper run, so no players/coaches exist yet) -- expected and
documented in the workflow file itself, not a surprise. CI badge added to
README.md.

All four of Fable's production-hardening items (4-7) are now done. What's
NOT done from either review: team-level fantasy scoring aggregation (the
biggest product-completeness gap, still blocked on players.position for
the "real" version), crash-recovery for a fully-dead idempotency claim,
and a `(user_id, league_id)` unique constraint on fantasy_teams.

## problemV16.md (Codex) -- all 6 findings fixed, same discipline as before (2026-09-07)

Codex reviewed everything up to commit `4574f65` and wrote
`Problems/problemV16.md` (6 findings: 3 P1 security, 2 P2, 1 P1-for-tests).
Same standing practice as every prior round: each was independently
verified (either by reading the actual code path, or reproducing it live
through the real app) before being fixed, not trusted on word.

1. **Reset-password race (P1)** — `reset_password` read the token with a
   plain `SELECT`, no locking. Two concurrent requests carrying the same
   still-valid token could both read it as valid before either committed,
   both successfully set a (different) new password, with no error to
   either caller. Fixed with `select(User)...with_for_update()`: the lock
   is held from the read through the commit (including the slow bcrypt
   hash — same tradeoff as `create_team`'s Season lock), and the token is
   cleared on the SAME row before the hash runs. A concurrent request
   blocks on the lock, then Postgres re-checks its WHERE clause against the
   now-committed (token now NULL) row before granting it, so it correctly
   finds no match instead of proceeding. Verified with a real test hitting
   the actual endpoint through the ASGI app against the real dev Postgres
   DB with two genuinely concurrent requests via `asyncio.gather`
   (`test_reset_password_race_only_one_concurrent_request_succeeds`) — not
   just an isolated reproduction of the query.
2. **Reset doesn't invalidate old JWTs (P1)** — a token issued before a
   password reset kept working normally until its own 7-day expiry, even
   though the reset was presumably a response to a suspected compromise.
   Fixed with a new `users.credentials_version` column (migration
   `09f392236159`), embedded in every JWT as `"cv"` and checked against the
   user's current value on every request (`app/deps.py`); a successful
   reset increments it, invalidating every previously-issued token
   everywhere at once. Verified with a real test: token obtained before
   reset gets 401 on `/api/auth/me` immediately after, a token obtained
   after the reset works normally
   (`test_reset_password_invalidates_previously_issued_tokens`).
3. **Email tokens logged unconditionally outside development (P1)** —
   `send_email` logged the full body (which carries a live verification or
   reset token) regardless of environment. Fixed: full body only logs when
   `settings.environment == "development"`; everywhere else, only a
   token-free notice is logged. The underlying limitation (no real email
   provider) is unchanged and still honestly surfaced — this only stops
   the token itself from ending up in a shared/persisted log sink.
4. **Cache fallback doesn't actually dedupe without Redis, and its lock
   dict never shrinks (P2)** — the previous per-key-`asyncio.Lock` version
   of `get_or_compute_json` only serialized concurrent callers for the same
   key; it never shared the *result*, so with caching disabled (no Redis,
   or Redis down) 25 concurrent callers still ran `compute()` 25 times,
   just one at a time instead of in parallel -- confirmed independently by
   Codex (263ms for a ~10ms compute) before I fixed it. The lock dict also
   never removed entries, growing without bound across the real key space
   (confirmed: 200 unique keys left 201 dead locks). Rewrote it around a
   single shared in-flight `asyncio.Task` per key instead of a lock: every
   concurrent caller awaits the SAME task, and the entry is removed the
   moment it finishes (success or failure) — fixes both problems in one
   change. Verified with 3 tests: the original 25-concurrent-with-Redis
   case still works, a new 25-concurrent-*without*-Redis case (the actual
   regression) now also computes exactly once
   (`test_concurrent_misses_compute_once_even_without_redis`), and a
   200-unique-key test confirms the dict is empty once every call has
   finished (`test_inflight_dict_does_not_grow_unbounded`).
5. **Legacy lockout counters missing a TTL stay locked out forever (P2)** —
   `_increment_with_ttl`'s self-heal (added in the problemV15 round) only
   runs on an *increment*, but `login` calls the read-only `check_lockout`
   FIRST — so an account already at/over the limit with a damaged (TTL -1)
   counter returns 429 forever with no code path that ever reaches the
   healing logic. Reproduced with fakeredis (a counter manually set to 5
   with no TTL stayed at TTL -1 and locked out indefinitely) before fixing:
   `check_lockout` now self-heals a missing TTL itself, given the same
   `window_seconds` `record_failed_attempt` uses
   (`test_check_lockout_self_heals_legacy_counter_without_ttl`).
6. **Test suite wipes `ratelimit:*` on WHATEVER Redis DB is configured,
   including a real shared one (P1 for the test environment)** — the
   autouse fixture in `conftest.py` scans and deletes every `ratelimit:*`
   key before each test on whatever `REDIS_URL` resolves to; running pytest
   with the same `.env` a real dev/prod server uses would delete real
   rate-limit/lockout state, not just test leftovers. Fixed by forcing the
   whole test session onto a dedicated logical Redis DB (15) regardless of
   whatever db number the configured URL already has — done once at
   `conftest.py` import time by rewriting `settings.redis_url`'s path.
   Verified manually: ran the lockout test with `REDIS_URL` pointing at the
   normal dev Redis, confirmed keys landed on db 15
   (`redis-cli -n 15 keys ratelimit:*` showed them) while db 0 stayed at
   `dbsize` 0 throughout the entire suite, both before and after.

Full suite: 47 passed (was 42; +5 new tests for these fixes), both with and
without `REDIS_URL` set (45 passed + 2 skipped without it, matching the 2
`requires_redis`-marked lockout tests).

Not addressed by this round, called out in problemV16.md itself as still
open (nothing new here, same items already tracked elsewhere in this file):
CI still skips 6 integration tests needing real roster data; logging isn't
an alerting system; team-level scoring aggregation, idempotency
crash-recovery, and the `(user_id, league_id)` unique constraint remain
open.

## problemV17.md (Codex) -- reproducible backfill + duplicate-identity fix (2026-09-07)

Codex reviewed the two documentation-only commits after problemV16
(`ccb30e3`, `180009a`) and correctly pointed out they were exactly that --
docs only, no application code, so none of problemV16's 6 findings were
actually fixed by them (they've since been fixed, see the section above,
same session). Two NEW findings in this review, both real and both fixed:

1. **The position/coach backfill wasn't reproducible from the repo (P1)** —
   `git diff --stat` between those commits showed only `CONTINUE.md` and
   the handoff doc; the actual backfill was done via throwaway scripts in
   `/tmp`, never committed. A fresh checkout + migration could not
   reproduce the 348 positioned players or the 13 real coach names at all.
   Fixed: `scripts/backfill_positions_and_coaches.py` is now a real,
   committed, idempotent script — the source file itself
   (`scripts/data/rosteri2.0.txt`, the user's manually-reviewed roster
   export) is also committed, so the whole thing re-derives from the repo,
   not from memory of what I ran in a scratch directory. Matches by
   `(real_club, name)`, not local UUIDs (which wouldn't exist in a fresh
   DB). Verified idempotent: ran it twice, identical output both times
   (`Position updates: 328` both runs).
2. **Placeholder positions were indistinguishable from real ones in the API
   (P2)** — `PlayerOut` returned only `position`, with no way to tell
   Cattaro's 23 hand-guessed placeholder positions apart from the 348 the
   user actually reviewed; both the docs and (per Codex) the frontend's own
   copy were calling all of them "confirmed." Fixed: new
   `players.position_verified` column (migration `feaae23bb208`, default
   `true`), set to `false` only for Cattaro's 23 rows, exposed on
   `PlayerOut`. Formation validation in `save_lineup` still accepts any
   non-null position regardless of this flag (a placeholder position is
   still a position for gameplay purposes) — this is purely a
   provenance/UI signal, not a new gameplay gate; the frontend is
   responsible for whatever visual distinction it wants to make with it.

**A third finding, not new but re-surfaced with a sharper edge** ("nije
potvrđen duplikat identiteta" -- duplicate identity not confirmed): Codex
cautioned that applying one position to both rows of a 24 shared-name pairs
doesn't prove they're the same person, and warned against any automatic
merge. Investigating this surfaced something worth fixing on its own
merits, not just addressing the caution: **all 24 pairs turned out to have
exactly one row WITH a stable `external_id` and one row WITHOUT** — this
matches the scraper's own long-documented, independently-verified behavior
that goalkeepers never get a stable id (`scraper/player_resolver.py`),
while field players always do. The original backfill's "same position for
both" approach therefore likely mislabeled several real field players as
goalkeepers (whenever the source file's only data point for a shared name
was "GK"). `backfill_positions_and_coaches.py` now treats the
no-`external_id` row as the goalkeeper unconditionally, and applies the
file's given position to the `external_id` row only when that value isn't
itself "GK" (18 of the 24 pairs' field-player rows lost their position as a
result — from `GK`, wrongly, to `NULL`, honestly; 5 pairs kept a real
non-GK position on the field-player row; a 24th pair, Valis Vega's "Veljko
Babić"/"Veljko Babic", has BOTH rows with an external_id — doesn't fit this
shape at all, so the script correctly leaves it untouched rather than
guessing). Net effect: positioned-player count dropped from 348 to 330,
which is the correct direction — honest is better than complete here.
**Not a merge**: both rows of every pair still exist as distinct catalog
entries; whether any of these 24 pairs are actually the same real person
(vs. two different people who happen to share a name) is still genuinely
unresolved and would need real identity verification (match history,
external site cross-reference) before anyone should act on it further.

Full suite still 47 passed after this. `scripts/data/rosteri2.0.txt` and
`scripts/backfill_positions_and_coaches.py` are both new, committed files.

## Suggested next steps, roughly in order

1. Decide with the user which of Fable's findings to prioritize next --
   team-level scoring aggregation (the biggest product gap, but the
   "real" version depends on players.position/lineup which is blocked;
   could build a roster-based interim version now, or wait) vs. the
   production-hardening items (rate limiting is cheap and independent of
   any blocker; email verification, CI, observability are all also
   independent and could be picked up any time).
2. When the position/coach file arrives: backfill `players.position` and
   real `Coach` names, then build lineup management properly (Codex's
   tested API shape is already merged into `main`'s `teams.py`), and real
   (not interim) team-level scoring.
3. Reconcile with the `frontend` branch again once Codex has rebased onto
   the merged `main` (see the merge section above) -- most hard conflicts
   are already resolved there, so this should be a thinner pass.
4. Goalkeeper ID resolution via a team-squad page sample, if/when convenient.
5. Everything else is tracked in `docs/Fantasy_Waterpolo_Arhitektura_v2.md`,
   Section 7 — that list is kept current; trust it over memory of what "next
   steps" were at any earlier point in this file.
