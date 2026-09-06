from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.routers import auth, coaches, competitions, home, matchdays, matches, players, teams

app = FastAPI(title="Waterpolo Fantasy API")

# Read-only, shared (not per-user) data -- only changes when the scraper
# writes new results, never per-request.
_CACHEABLE_PREFIXES = (
    "/api/competitions",
    "/api/players",
    "/api/coaches",
    "/api/matches",
    "/api/matchdays",
    "/api/home",
)
# Per-user or financial -- explicit `private, no-store` rather than just
# omitting a cache header, per the frontend session's review: don't rely on
# "no header" to mean "don't cache" for an intermediate proxy/CDN.
_PRIVATE_PREFIXES = ("/api/auth", "/api/teams")


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or "Cache-Control" in response.headers:
            return response
        if request.url.path.startswith(_PRIVATE_PREFIXES):
            response.headers["Cache-Control"] = "private, no-store"
        elif request.url.path.startswith(_CACHEABLE_PREFIXES) and response.status_code == 200:
            response.headers["Cache-Control"] = f"public, max-age={settings.cache_control_max_age_seconds}"
        return response


app.add_middleware(CacheControlMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(auth.router)
app.include_router(competitions.router)
app.include_router(players.router)
app.include_router(coaches.router)
app.include_router(matches.router)
app.include_router(matchdays.router)
app.include_router(teams.router)
app.include_router(home.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
