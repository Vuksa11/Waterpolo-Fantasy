from fastapi import FastAPI

from app.routers import auth, coaches, teams, competitions, lineups, matchdays, matches, players

app = FastAPI(title="Waterpolo Fantasy API")

app.include_router(auth.router)
app.include_router(coaches.router)
app.include_router(teams.router)
app.include_router(competitions.router)
app.include_router(players.router)
app.include_router(lineups.router)
app.include_router(matches.router)
app.include_router(matchdays.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
