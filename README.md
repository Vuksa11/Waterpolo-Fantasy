# Waterpolo Fantasy

Classic-style fantasy waterpolo platform covering three competitions: Regionalna liga,
Super liga Srbije, and Prva liga Srbije. No draft — all managers pick from the same
credit-budgeted player pool. Player/match data is scraped from totalwaterpolo.com by a
Python scraper (no paid third-party API).

Full architecture, data model, and scoring rules: [`docs/Fantasy_Waterpolo_Arhitektura_v2.md`](docs/Fantasy_Waterpolo_Arhitektura_v2.md).

## Project layout

```
backend/    FastAPI application + Alembic migrations (v1 API)
scraper/    Python scraper for totalwaterpolo.com (schedules + box scores)
docs/       Architecture documentation
```

## Local development

```bash
cp .env.example .env
docker compose up -d db
pip install -r requirements.txt

# from backend/
alembic revision --autogenerate -m "initial schema"
alembic upgrade head

# run the API
uvicorn app.main:app --reload --app-dir backend
```

## Status

Scaffolding stage — data model and migration setup are in place; scraper parsers
(`scraper/parsers/`) are stubbed pending a sample totalwaterpolo.com page per
competition (see docs, Section 7 — Next Steps).
