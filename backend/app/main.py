from fastapi import FastAPI

from app.routers import competitions, matchdays, matches, players

app = FastAPI(title="Waterpolo Fantasy API")

app.include_router(competitions.router)
app.include_router(players.router)
app.include_router(matches.router)
app.include_router(matchdays.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
