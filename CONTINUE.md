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

## Blocked on the user

- **`players.position`** (OT/CF/CB) — null for every player. Not scrapeable
  (confirmed absent from the match box-score page). The user said they'll
  send a reference file. This blocks: lineup/formation validation, and the
  frontend's team-builder (which correctly disables buying any player until
  this exists).
- **Real coach names** — every club currently has one generic placeholder
  `Coach` row (name suffixed "— trener TBD"). Same file as positions, per the
  user.
- **Goalkeeper stable IDs** — field players get a stable external id
  straight from the box score; goalkeepers don't (confirmed, not a bug).
  Needs a team-squad page sample to resolve properly; currently matched by
  (name, club) instead. Not blocking anything today, just less robust.

## Suggested next steps, roughly in order

1. When the position/coach file arrives: backfill `players.position` and
   real `Coach` names, then build lineup management (adopt Codex's tested
   API shape rather than designing fresh).
2. Check in on `FantasyWP-frontend` and merge when both sides are ready
   (watch for the alembic branching noted in the handoff doc — two
   migrations may share a `down_revision` and need reconciling).
3. Goalkeeper ID resolution via a team-squad page sample, if/when convenient.
4. Everything else is tracked in `docs/Fantasy_Waterpolo_Arhitektura_v2.md`,
   Section 7 — that list is kept current; trust it over memory of what "next
   steps" were at any earlier point in this file.
