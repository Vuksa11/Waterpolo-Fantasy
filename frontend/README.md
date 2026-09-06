# VRL Fantasy frontend

Responsive implementation based primarily on the user's Claude design handoff. Vanilla ES modules keep this prototype dependency-free and split UI, API transport, demo fixtures and lineup rules. No design runtime/support.js is shipped.

## Run

Requires Node20+ and the Python dependencies from the repository requirements.

```bash
# Repository root, activate your Python virtual environment first:
PYTHONPATH=backend:. python -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# Separate terminal:
cd frontend
API_TARGET=http://127.0.0.1:8001 npm run dev
```

Open http://localhost:3000. The development server serves static assets and proxies `/api/*` to FastAPI. It is not a production deployment server. The browser never receives DB credentials or JWT signing secrets. JWT access token is session-scoped; logging out clears it locally (server token revocation is not implemented).

## Data and behavior

Demo mode starts with a complete 11-player + coach team. API mode uses actual competitions/players/coaches/rounds/matches/standings from the configured database. No automatic fallback to invented API data. Preview DB setup is explained in `DATA_SOURCE.md`; the sports snapshot is not a live feed.

- THREE_THREE: GK1 OT4 CF1 CB1.
- FOUR_TWO: GK1 OT4 CF2 CB0.
- TWO_FOUR: GK1 OT4 CF0 CB2.
- Bench: GK1 OT2 and one CF/CB; coach is separate.
- Changing formation retains the entire roster, leaving missing roles empty.
- Local drafts are separated by source, competition and logged-in user.
- API team creation, atomic transfers and lineup writes use Bearer auth; server checks ownership, real DB prices, verified positions, deadlines and expected version.
- Transfers clear saved future lineups; managers must re-save. Closed/missing deadlines are refused.
- Real players currently have no confirmed positions and rounds have no deadlines. These are data prerequisites; demo mode allows the full UI to be exercised without fabricating production data.

## Tests

```bash
npm test
npm run check
# From repository root:
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -v
# Optional real PostgreSQL+browser check, only isolated frontend DB and running dev services:
PYTHONPATH=backend:. python scripts/verify_frontend_e2e.py
```

Browser checks cover all routes at320,390,768,1024,1440 widths, three formations, empty-role feedback, substitutions, captain, reload persistence, pool/list mode, real login and save. PostgreSQL tests cover simultaneous registration, version conflict and transfer attempts; fixtures are cleaned afterward. Synthetic10,010-player catalog tests prove bounded pagination, not an unlimited user capacity guarantee.

Design rationale/sources: `../docs/DESIGN_DECISIONS.md`. Integration contract: `../docs/FRONTEND_BACKEND_HANDOFF.md`.

### Učitavanje i ponovljeni zahtevi

Početna koristi javni `GET /api/home?competition_id=...`. Stariji backend koji
vrati 404 koristi postojeće matchdays/matches rute. Ostali javni blokovi učitavaju
se nezavisno, sa zasebnim stanjem greške. Katalog pamti najviše 40 javnih rezultata,
sa rokom 30 sekundi; transfer briše javni keš. Privatni timovi ne ulaze u taj keš.

Kreiranje tima i transfer šalju `Idempotency-Key`. Isti neizvesni zahtev zadržava
ključ u sessionStorage i memoriji za ručno ponavljanje; paralelni isti zahtevi dele
jedan poziv. Ključ se odvaja po tokenu, putanji i telu preko SHA-256; token se ne
čuva u identifikatoru ključa. Posle neizvesnog PUT sastava front čita server i
proverava da li je traženi sastav već sačuvan, bez slepog ponavljanja upisa.

Serverska podrška je obavezna za garanciju idempotentnosti. Backend ove frontend
grane još nije dobio Claudeovu idempotency implementaciju. Njegov main, zasebno,
još čeka usklađivanje proširenog team/lineup ugovora i oporavak pending zahteva.
Slanje header-a samo po sebi ne rešava te backend zavisnosti.

Browser test sa izolovanim API odgovorima (bez upisa u bazu):

```bash
CHROMIUM_PATH=/putanja/do/chromium python scripts/test_frontend_browser.py
```

Pokrenuti iz korena repozitorijuma uz aktivan frontend na 3000, Python Playwright
paket i Chromium. `FRONTEND_URL` može promeniti adresu. Ovaj test potvrđuje frontend
ugovor, ne predstavlja live PostgreSQL integracioni test niti test opterećenja.
