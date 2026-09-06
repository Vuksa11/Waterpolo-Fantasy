import hashlib

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response

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
        if "Cache-Control" in response.headers:
            return response
        # Checked before the GET-only branch below on purpose: the frontend
        # session's review caught a version of this that returned early for
        # any non-GET method first, so POST /api/auth/login and
        # POST /api/teams/... -- most of what those routers actually do --
        # got no Cache-Control header at all instead of the intended
        # `private, no-store`.
        if request.url.path.startswith(_PRIVATE_PREFIXES):
            response.headers["Cache-Control"] = "private, no-store"
            return response
        if (
            request.method == "GET"
            and request.url.path.startswith(_CACHEABLE_PREFIXES)
            and response.status_code == 200
        ):
            response.headers["Cache-Control"] = f"public, max-age={settings.cache_control_max_age_seconds}"
            return await _add_etag_and_maybe_304(request, response)
        return response


async def _add_etag_and_maybe_304(request: Request, response: Response) -> Response:
    """
    ETag was part of the original Phase-1 plan (docs/FRONTEND_BACKEND_HANDOFF.md)
    alongside Cache-Control but never actually implemented -- only added now.
    Only for public, cacheable GET responses (private/auth/teams routes never
    reach here): saves the full response bytes on a client's repeat GET
    within the max-age window even after that window expires, since a
    conditional request with a matching If-None-Match still gets a 304 with
    no body instead of a full re-fetch.

    Hashed on the plain (pre-gzip) JSON body -- this middleware runs *inside*
    GZipMiddleware in the stack (added first == innermost, per Starlette's
    ordering), so it sees the response before compression, and the ETag stays
    stable regardless of whether a given client negotiates gzip.
    """
    body = b"".join([chunk async for chunk in response.body_iterator])
    etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'

    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and etag in {tag.strip() for tag in if_none_match.split(",")}:
        return Response(status_code=304, headers={"Cache-Control": response.headers["Cache-Control"], "ETag": etag})

    new_response = Response(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
    new_response.headers["ETag"] = etag
    return new_response


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
