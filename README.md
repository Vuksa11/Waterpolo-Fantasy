# Waterpolo Fantasy

Classic-style fantasy waterpolo platform covering two regional competitions —
**Regionalna liga** (VRL Premier Liga) and **VRL Prva Liga** (second tier).
No draft — all managers pick from the same credit-budgeted player pool.
Player/match data is scraped live from totalwaterpolo.com by a headless-browser
Python scraper (no paid third-party API).

Full architecture, data model, scoring rules, and project history:
[`docs/Fantasy_Waterpolo_Arhitektura_v2.md`](docs/Fantasy_Waterpolo_Arhitektura_v2.md).

## Project layout

```
backend/    FastAPI application (read-only sports-data API for now) + Alembic migrations
scraper/    Python/Playwright scraper for totalwaterpolo.com (schedules + box scores)
scoring/    Fantasy point calculation and the price-change formula
db/         Shared SQLAlchemy models + session factory (used by backend, scraper, and scoring)
docs/       Architecture documentation
```

`db/` and `scoring/` are separate top-level packages (not nested under `backend/`)
specifically so the scraper can import them without depending on the backend app,
and vice versa.

## Local development

```bash
cp .env.example .env   # then edit DATABASE_URL / DATABASE_URL_SYNC for your local Postgres
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# from backend/
../.venv/bin/python -m alembic upgrade head

# run the scraper pipeline once (schedule + box scores + scoring + prices)
DATABASE_URL_SYNC=postgresql+psycopg2://... .venv/bin/python -m scraper.run

# run the API (needs both the repo root and backend/ on the path, since
# app/ lives under backend/ but db/ and scoring/ live at the repo root)
PYTHONPATH=.:backend DATABASE_URL=postgresql+asyncpg://... \
  .venv/bin/uvicorn app.main:app --reload --app-dir backend
```

API docs (Swagger UI) once running: `http://localhost:8000/docs`.

## Status

- **Scraper**: working and verified live against both tracked leagues (132 matches,
  352 players, 3618 player_stat rows). Not yet resolved: goalkeeper stable IDs
  (needs a team-squad page), player positions and real coach names (pending a
  reference file from the project owner).
- **Scoring & pricing**: implemented and verified against the full real dataset.
- **API**: read-only sports-data endpoints (competitions, standings, players,
  matches, matchdays, top performers). No auth or fantasy-team layer yet.

See docs, Section 7 (Next Steps) for the full remaining list.

## Frontend branch

The integrated responsive client lives in [frontend/](frontend/README.md). Start FastAPI on8001 and run `API_TARGET=http://127.0.0.1:8001 npm run dev` from frontend to preview on http://localhost:3000.

See [API coordination](docs/FRONTEND_BACKEND_HANDOFF.md) and [design decisions](docs/DESIGN_DECISIONS.md). Apply Alembic migrations before using team writes; never treat unverified positions or missing deadlines as playable data.
