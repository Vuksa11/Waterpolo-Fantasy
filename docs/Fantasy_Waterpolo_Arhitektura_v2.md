# Waterpolo Fantasy — Architecture Document v2

**v2.0 — September 5, 2026**

**Nikola Vuksanović** — Lead Software Architect

Supersedes: `Fantasy_Waterpolo_Arhitektura_v1.pdf` (v0.1, March 19, 2026). This revision replaces the paid Sports Data API with a self-built Python scraper against totalwaterpolo.com, scopes the platform to three specific leagues, and resolves all open questions (OQ-1 through OQ-6) left unanswered in v1.

---

## 1. Overview

Waterpolo Fantasy is a web (v1) and mobile (v2) fantasy sports platform built around three real-world competitions:

- **Regionalna liga**
- **Super liga Srbije**
- **Prva liga Srbije**

Users build a **classic** fantasy roster (no draft — everyone picks from the same player pool, constrained by a shared credit budget) per competition and compete for the highest cumulative point total over the season. There are no user-created leagues in v1 — one global public league exists per competition per season. The schema keeps room to add private/user-created leagues later without migration.

## 2. Scope

### 2.1 Version 1 — In Scope

- League creation is **not** user-facing in v1 — one global league per competition is created automatically by the platform.
- Team building (classic style, budget-constrained) per competition.
- Lineup management per matchday, with formations (3×3 / 4×2 / 2×4).
- Transfers, unlimited per transfer window (see Section 8).
- One wildcard per season, usable only during a transfer window (not mid-matchday).
- Price changes computed automatically after each matchday (Section 8).
- Standings & stats — per-competition leaderboard, plus an overall cross-competition ranking.
- Data ingestion via a Python scraper against totalwaterpolo.com — **no third-party paid API**.

### 2.2 Out of Scope for v1

- User-created private/public leagues (schema supports it, UI does not expose it).
- Head-to-head weekly matchup format.
- Mobile app (targeted for v2; web ships first).
- Redis / live SSE score streaming (see Section 5.4 — deferred until load requires it).
- Claude-driven self-healing of scraper parsers (see Section 4.3 — optional add-on, not required for launch).

## 3. Glossary

Definitions below carry over unchanged from v1 unless noted.

- **Competition** *(new)* — one of the three real-world leagues (Regionalna liga, Super liga Srbije, Prva liga Srbije). Scopes seasons, player pools, and the global league.
- **League** *(fantasy)* — a group of users competing together. In v1, exactly one global, public league exists per competition per season, auto-created by the platform (no admin, no invite code).
- **Team** — a user's roster within one competition's global league. A user may hold up to 3 teams (one per competition).
- **Roster** — 12 slots: 2 GK, 9 field players (OT/CF/CB per formation), 1 coach. Bench players score at 50%.
- **Formation** — 3×3, 4×2, or 2×4 (unchanged from v1 — see Section 6.3 of the original document for exact slot breakdowns).
- **Position** — GK, OT, CF, CB.
- **Credits** — 100 starting budget per team per competition. Base price for every player/coach at season start is **7 credits** (flat, not position-scaled — subject to revision after testing).
- **Player Cost / Price Change** — now computed by a deterministic formula from scraped performance data (Section 8), not from a third-party feed.
- **Matchday** — a scoring period; may contain multiple real matches.
- **Transfer** — unlimited per transfer window in v1 (see Section 8 — OQ-4 resolved).
- **Wildcard** — one per season, usable only during a transfer window, not mid-matchday (Section 8 — OQ-3 resolved).
- **Standings / Overall Ranking** — unchanged from v1, but standings are now naturally per-competition since leagues are 1:1 with competitions.
- **Scraper** *(new, replaces "Sports Data API")* — the Python component that pulls schedules and box scores from totalwaterpolo.com on a fixed schedule and writes directly to PostgreSQL.

## 4. Data Ingestion — Python Scraper

The v1 architecture document's `ingest` Go module (polling a paid Sports Data API) is removed entirely. It is replaced by a standalone Python component with no dependency on the web backend's language or runtime.

### 4.1a Data Source — Verified Against a Real Match Page

**A match page is not static HTML.** `totalwaterpolo.com` runs a WordPress plugin (`totalwaterpolo-prod`) that renders the match widget client-side: the page ships a placeholder tag (`<tw_match_expanded matchid="12681">`) and JavaScript (`twa-match.js`, `twa-api.js`) fills it in by calling the site's own backend, `https://arena.total-waterpolo.com/api/` (`Matches/`, `Events/`, `Players/stats`, `Teams/`, `Competitions/`, `Clubs/`, plus a SignalR hub for live matches — all documented in that plugin's own code comments).

That API requires a Bearer token, confirmed by direct test (`401` without one). The token is meant to be injected server-side into the page for any visitor's browser, so this is not a paid or access-controlled partner API — but a plain `requests.get()` on the match URL only returns the page shell; the token/data never appear in that response.

**Resolution: render the page in a headless browser (Playwright) instead of calling the API directly.** This reproduces exactly what a normal visitor's browser does — the site's own JS acquires the token and populates the DOM — with no token extraction or API reverse engineering involved. `scraper/fetch_boxscore.py` implements this: `playwright.sync_api` loads `https://total-waterpolo.com/tw_match/{id}`, waits for `.tw_full_match[tw-match-id]` to appear, then hands `page.content()` to the parser.

This was verified end-to-end against a real saved match (id `12681`, competition `2358`, Valis Vega 21–14 Stari Grad): `scraper/parsers/match_page.py` correctly parsed all 26 rostered players (11 field players + 2 goalkeepers per side), and summed per-player goals to *exactly* the final score on both sides (21 and 14) — a strong end-to-end correctness check, not just "the code runs."

**DOM contract** (see the module docstring in `scraper/parsers/match_page.py` for the full reference):

- Team/score: `.tw_full_match[tw-match-id][tw-competition-id]`, `[tw-data="hometeamgoals"/"awayteamgoals"/"status"]`, team logo `onclick="OpenTeamPage(<id>, '<name>')"`.
- Field players: `#homePlayers` / `#awayPlayers`, each `.tw_match_player[tw-player-id]` block. The name label's `onclick="OpenPlayerPage(<id>, '<name>')"` gives a **stable, cross-match player id directly in the box score** — this eliminates the fuzzy name-matching originally planned in Section 4.1 v1 (superseded); resolving a field player is a plain upsert-by-external-id.
- Per-player aggregate stats (plain text, not canvas) via `[tw-chart-id="<key>_<player-id>"] [tw-data="homeResult"]` (the attribute name is a generic chart-component label meaning "this player's count" in this nested context, not home-team): `assists`, `pfdrawn` (→ `fouls_drawn`), `steals`, `blocks`, `swimoffs`, `ballslost` (→ `turnovers`), `offensivef` (→ `offensive_fouls`), `pf` (→ `personal_fouls`).
- Goals, misses, and saves are **not** available as plain-text aggregates — the equivalent shots-made/attempted summary renders as a canvas doughnut chart with no scrapeable value. These are instead derived by counting `.tw_play_by_play[tw-event-id]` rows by their `.description` text (`goal scored` variants → goals; `shot missed` variants → misses; `Shot saved` → miss for the shooter + save for whoever the event's "saved by" detail field names).
- **Goalkeepers are a separate section** (`#homeGoalkeepers` / `#awayGoalkeepers`) and, unlike field players, their name label has **no** `OpenPlayerPage` onclick — no stable id is exposed on the match page for them. `scraper/player_resolver.py` is scoped to this one gap: resolving goalkeepers by name, pending a team-squad page sample that might expose a proper id the same way the match page does for field players.

**Known v1 simplifications** (documented in `match_page.py`, flagged here for visibility):
- `goals_conceded` is assigned to whichever goalkeeper on a team recorded the most saves in the match (proxy for "the starting keeper") and set to the opponent's full final score. A mid-match keeper substitution (backup keeper who also recorded a save or two) is not split out — the backup's saves are still counted correctly, but all `goals_conceded` for that team goes to the presumed starter.
- **Scoring model default:** "Miss" (−0.5) is counted only for `shot missed` / `Power play shot missed` events. A shot that was saved or blocked by the opponent still fails to score but is **not** counted as a miss for the shooter in v1 — treated as a contested attempt rather than a shooter error. Flag if you want saved/blocked attempts to also count as a miss for the shooter.
- **The fixture-list/schedule page is now implemented and verified too** (`scraper/parsers/schedule_page.py`), against a real saved competition page ("VRL Prva Liga 2025/26", competition id 2358): 72 fixtures parsed across 17 rounds, and match `12681` cross-checked byte-for-byte against the independently-parsed match page (same score, same teams, same round). Round grouping uses the site's own round label (e.g. "Termin 16") directly as the matchday identifier — there's no separate numeric round index. No kickoff date/time is exposed in this view (only on the individual match page), and no genuinely upcoming (unscored) fixture was available in the sample to verify that code path — flagged as an assumption in the module docstring, not yet proven against live data.

### 4.1 Component Structure

```
scraper/
├── fetch_schedule.py    # per-competition fixture list -> upsert matches/matchdays
├── fetch_boxscore.py    # per-match box score -> player_stats/coach_stats
├── parsers/              # ALL CSS/XPath selectors live here, isolated by page type
│   ├── schedule_page.py  # so a site redesign means editing one file, not the pipeline
│   └── match_page.py
├── player_resolver.py   # goalkeepers only, by name -- field players carry a
│                          # stable external id directly in the box score (4.1a)
└── run.py                # orchestrator entrypoint, invoked by cron/systemd timer
```

### 4.2 Pipeline (idempotent, safe to retry)

1. For each of the 3 competitions, refresh the fixture list — upsert into `matches` (status: UPCOMING / LIVE / FINISHED) and group into `matchdays`.
2. Select matches needing a box-score scrape: `LIVE` or `FINISHED` matches where `player_stats` is missing or stale (last update older than N minutes).
3. Fetch and parse the box-score page for each; upsert per-player statistics keyed by `(match_id, player_id)` — never insert-only, so a re-run after a parser fix self-heals old bad rows.
4. Invoke the scoring module to (re)compute `fantasy_scores` for the affected matchday.
5. On matchday finalization, run the price-change step (Section 8) and write `price_history`.
6. Log every run to a `scrape_runs` table (timestamp, matches processed, errors) — this is the only visibility into a parser silently breaking when the site changes.

### 4.3 Operational Notes

- **Rate limiting & etiquette** — respect robots.txt, fixed delay between page loads, identifiable User-Agent on the headless browser context. This is a public site being rendered like any visitor's browser, not an API partner — getting rate-limited or IP-blocked mid-match would be a self-inflicted outage. A headless browser is also heavier per request than a plain HTTP call (Section 4.1a) — the polling interval in Section 4.4 should account for that cost, not just politeness.
- **Raw HTML snapshots** *(recommended, low cost)* — store the fetched page alongside the parsed result so a broken parser can be diagnosed without waiting for a re-scrape.
- **Optional future addition — Claude-assisted self-healing**: a scheduled Claude Code cloud routine (e.g. weekly, or triggered by a run of consecutive `scrape_runs` errors) that reviews failures against current site HTML and proposes a fix to `parsers/`. This is explicitly **not** part of the production runtime — the pipeline itself is fully deterministic cron + Python, per the decision below.

### 4.4 Automation Model

Claude does **not** participate in triggering production scrapes. A cron/systemd timer invokes `run.py` on a fixed interval:

- Tighter interval (~5–10 min) during known match windows (weekends / active matchdays).
- Looser interval (~hourly) otherwise, to catch schedule changes.

`matchdays.deadline` (unchanged from v1) drives lineup locking using the same mechanism the cron already relies on for scrape timing.

## 5. System Architecture

### 5.1 Data Model Changes

Builds on the v1 entity set (`users`, `players`, `coaches`, `seasons`, `matchdays`, `matches`, `leagues`, `fantasy_teams`, `rosters`, `lineups`, `player_stats`, `coach_stats`, `fantasy_scores`, `transfer_history`, `price_history`) — all definitions and the polymorphic entity reference pattern (Section 6.2 of v1) carry over unchanged. Additions:

- **`competitions`** *(new table)* — `id`, `name`, `source_slug` (totalwaterpolo identifier). Root of the new scoping hierarchy.
- **`seasons.competition_id`** *(new FK)* — a season now belongs to exactly one competition.
- **`players.competition_id`** / **`coaches.competition_id`** *(new FK)* — player pools and credit budgets are scoped per competition; the same real person could in principle appear in more than one competition as a distinct pool entry.
- **`leagues`** — unchanged shape (`visibility` ENUM `PRIVATE`/`PUBLIC` already existed in v1). In v1 exactly one row per `(competition_id, season_id)` is created by the platform with `admin_id = NULL`, `visibility = PUBLIC`. No schema change is needed to later allow user-created leagues — only a UI change.
- **`scrape_runs`** *(new table)* — `id`, `started_at`, `finished_at`, `matches_processed`, `error_count`, `notes`. Operational log for the scraper (Section 4.2).

No draft-related tables exist or are planned — team building was already "classic" (budget draft from a shared pool) in v1, unchanged here.

### 5.2 Scoring (unchanged from v1 — Section 6.5 of the original document)

**Field players (OT, CF, CB):** Goal +3.0, Assist +1.0, Foul drawn +1.0, Steal +1.0, Block +1.0, Swim-off won +1.0, Miss −0.5, Personal foul −1.0, Turnover −1.0, Offensive foul −1.0.

**Goalkeeper (additional):** Save +1.5, Goal conceded −0.5.

**Coach:** Win by 1–2 → +4, 3–5 → +6, 6–8 → +10, 9+ → +12. Draw → 0. Loss by 1–2 → −2, 3–5 → −4, 6–8 → −6, 9+ → −8.

**Multipliers:** Bench slot ×0.5, Captain (active players only) ×2.0 — mutually exclusive. Coach is never eligible for captaincy.

This is carried over 1:1 because totalwaterpolo.com provides full per-player box scores (goals, assists, steals, blocks, fouls drawn, misses, personal fouls, turnovers, offensive fouls, GK saves/goals conceded) for all three competitions — confirmed before this revision was written.

### 5.3 Tech Stack — Version 1 (web-first, launch target)

| Concern | Technology | Rationale |
|---|---|---|
| Backend | **Python (FastAPI)** | Same language as the scraper — one mental model, one repo, simpler ops for a small/solo team. Go's concurrency advantage (many simultaneous SSE clients) isn't needed at this scale (3 competitions, small early user base). |
| Frontend | **React (Next.js)**, web only | "Web first" per product decision. SSR helps initial load on standings/stats pages; shares an API contract that a future mobile client can reuse. |
| Database | **PostgreSQL** | Transactional guarantees for transfer/credit-balance logic, same reasoning as v1. |
| Cache / live scoring | **None in v1** | At this scale, live scores can be served directly from Postgres (short-poll or simple refresh) without Redis/SSE. Added back in v2 if load requires it — avoids solving a scaling problem that doesn't exist yet. |
| Scraper | Python, cron/systemd timer, writes directly to Postgres | No message broker or intermediary — fewest moving parts. |
| Deployment | Docker Compose (API + scraper cron + Postgres) on a single VPS (DigitalOcean) | Mirrors v1's infra choice; keeps a straightforward path to self-hosting later. |

### 5.4 Tech Stack — Version 2 (scale + mobile)

| Concern | Technology | Rationale |
|---|---|---|
| Backend | **Go**, modular monolith (as in v1) | Reintroduced once concurrent SSE clients / traffic justify it. |
| Scraper | Python, kept as an **independent service** writing to the same Postgres instance | Scraping is I/O-bound (language doesn't matter) and changes far more often than the API (site redesigns) — isolating it avoids coupling scraper churn to backend deploys. |
| Frontend | React Native + Expo (mobile) alongside the existing Next.js web app | Shared backend API contract, per the original v1 plan. |
| Cache | Redis (live scoring + SSE backing store) | Reintroduced when traffic justifies it. |
| Everything else | JWT auth, `sqlc`, `golang-migrate` (unchanged from v1) | These were already sound choices independent of the API vs. scraper decision. |

Migration from v1 to v2 is a backend API rewrite (Python → Go) against an unchanged Postgres schema; the scraper and database are untouched, which is the reason for treating the scraper as its own component from day one rather than embedding it in the API process.

## 6. Resolved Open Questions (from v1 Section 8)

### OQ-1: HTTP routing library
Superseded — v1 backend is now FastAPI (Python), which has its own routing built in. Not applicable to v2's Go backend until that phase starts; Chi vs. Gin decision deferred to v2 planning.

### OQ-2: Price change algorithm — **RESOLVED**

Price tracks a player's own recent scoring output, using a 3-matchday rolling average as the target, smoothed to avoid single-game volatility.

```
target_price(player, matchday) = average(raw_fantasy_points over last min(3, matchdays_played))

gap   = target_price - old_price
step  = clamp(0.3 * gap, -MAX_DROP, +MAX_RISE)
new_price = clamp(old_price + step, FLOOR, CEILING)
```

- **Base price**: 7 credits for every player and coach at season start (flat, not position-scaled — revisit after testing).
- `raw_fantasy_points` is pre-multiplier (i.e. `fantasy_scores.raw_points`) — a player's price reflects intrinsic performance, not whether some fantasy manager benched them.
- **Recommended parameters** (tune after testing, per product owner's own note): `MAX_RISE = 1.0 CR`/matchday, `MAX_DROP = 1.0 CR`/matchday (symmetric for v1 simplicity — can be made asymmetric, e.g. slower drop, on request), `FLOOR = 4 CR`, `CEILING = 20 CR`.
- The 0.3 smoothing factor means price moves 30% of the way toward the 3-matchday average each matchday rather than jumping directly to it — reacts within 3–4 matchdays without single-game whiplash.
- Coaches use the same mechanism and base price; their naturally different point range (win/loss margin scoring) will settle at its own equilibrium without a separate formula.
- Computed as the final step of matchday finalization in the scoring module, immediately after `fantasy_scores` are written; result appended to `price_history`, `players.current_cost` / `coaches.current_cost` updated. The existing v1 `credit_balance` formula (`100 + Σ sell prices − Σ buy prices`) requires no changes.

### OQ-3: Wildcard rules — **RESOLVED**
One wildcard per season. Usable only during a transfer window (not while a matchday is active/live).

### OQ-4: Transfer limit — **RESOLVED**
No limit. Users may make unlimited transfers within any transfer window.

### OQ-5: Captain eligibility edge cases
Not yet explicitly revisited in this revision — default carried from v1 intent: if a captain's real-world match has already kicked off, their lineup slot (and captaincy) locks for that matchday; if the match is cancelled/postponed, the captain multiplier does not apply (reverts to standard ×1) since no stats are produced. Flag if a different behavior is wanted.

### OQ-6: Redis cold start and staleness strategy
Moot for v1 — Redis is not part of the v1 stack (Section 5.3). Applies only once v2 reintroduces it; carry the original open question forward to v2 planning.

## 7. Next Steps

1. ~~Confirm OQ-5 default~~ — done: captain multiplier does not apply (reverts to ×1) if the real-world match is cancelled/postponed.
2. ~~Obtain a sample match page and lock down `parsers/match_page.py` selectors~~ — done and verified end-to-end against a real match (Section 4.1a): field players resolve via a stable id in the box score, goalkeepers need name resolution, goals/misses/saves derive from play-by-play, everything else from per-player aggregate charts.
3. ~~Scaffold repository structure~~ — done: FastAPI backend, SQLAlchemy models, Alembic migration setup, Docker Compose, all pushed to `Vuksa11/Waterpolo-Fantasy`.
4. ~~Obtain a sample fixture-list page and write `scraper/parsers/schedule_page.py`~~ — done and cross-checked against the match page parser (Section 4.1a).
5. ~~Generate and run the first Alembic migration against a live Postgres~~ — done. Installed Postgres locally, ran it for real, and it caught a genuine bug (the `position` enum type name collided with Postgres's reserved `POSITION(... IN ...)` syntax — renamed to `player_position`).
6. ~~Wire up the DB upsert layer~~ — done (`scraper/db_writer.py`); `fetch_boxscore.py`/`fetch_schedule.py`/`run.py` write to the database for real. Goalkeeper name-resolution (`player_resolver.py`) is still a stub, pending a team-squad page sample.
7. **Scope change (2026-09-06):** Super liga Srbije and Prva liga Srbije are not on totalwaterpolo.com. The project now tracks the two VRL regional leagues instead — **Regionalna liga** (VRL Premier Liga 2025/26) and a second tier, **VRL Prva Liga 2025/26**. Both are fully scraped: 60 + 72 matches, 352 players, 3618 player_stat rows, live-verified against the real site (see git history for the session that did this).
8. ~~Implement the scoring module~~ — done (`scoring/engine.py`), verified against the full real dataset (3159 `fantasy_scores` rows). Resolved an ambiguity in the original v1 doc: `fantasy_scores` has no `fantasy_team_id`, so it cannot hold post-multiplier points for a specific team's lineup — `final_points` here equals `raw_points`; bench/captain multipliers apply later, per fantasy team, at lineup-scoring time (not yet built).
9. Verify the UPCOMING-fixture code path in `schedule_page.py` against a real not-yet-played match — both leagues sampled so far had fully finished seasons.
10. Stand up the two auto-created global leagues (one per competition) as part of proper season-creation logic — `db_writer.get_or_create_active_season` currently creates a placeholder season with today's date as both start and end, good enough for scraper development but not real season semantics.
11. ~~Implement the price-change formula~~ — done (`scoring/price.py`), verified against the full real dataset: prices for all 352 players ranged 4–14 CR (never hit the 20 CR ceiling), every single-matchday change was ≤1.0 CR as designed, and a spot-checked top scorer's price climbed smoothly from the 7 CR base to ~10.9 over 13 matchdays, dipping and recovering with form. Must run in ascending matchday-number order per season — each step's "old price" is whatever the previous step left on `players.current_cost` — `recompute_all_prices` enforces this for backfills; `scraper/run.py` does the same for its per-run touched matchdays.
12. Coach scraping and scoring — `coach_points()` exists in `scoring/engine.py` but nothing populates `coach_stats` yet; the officials section of a match page lists a "Delegate" role, not confirmed yet to include a coach role.
13. Resolve `players.position` (OT/CF/CB) — still null for every field player; the user is providing a reference file for this separately.
