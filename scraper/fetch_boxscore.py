"""
Fetches and renders a single match page via headless browser, then parses and
upserts its box score.

Pipeline steps 2-3 in docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2.

Why a headless browser instead of a plain HTTP GET: the match widget's data
(box score, play-by-play) loads client-side from a Bearer-token-gated API
(https://arena.total-waterpolo.com/api/) that returns 401 without the token,
which the site's own PHP injects only into a fully-loaded page context. A
headless browser reproduces exactly what a normal visitor's browser does — same
front door, no token extraction or API reverse engineering. Verified against a
real saved match page (12681) — see docs/Fantasy_Waterpolo_Arhitektura_v2.md,
Section 4.1a.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from playwright.sync_api import sync_playwright

from db.models import Match
from scraper.db_writer import get_or_create_competition, upsert_box_score
from scraper.parsers.match_page import ScrapedMatchBoxScore, parse_match_page

_MATCH_URL_TEMPLATE = "https://total-waterpolo.com/tw_match/{external_match_id}"
_RENDER_TIMEOUT_MS = 15_000


def render_match_page(external_match_id: int) -> str:
    """Load a match page in a headless browser and return the fully-rendered HTML."""
    url = _MATCH_URL_TEMPLATE.format(external_match_id=external_match_id)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".tw_full_match[tw-match-id]", timeout=_RENDER_TIMEOUT_MS)
        html = page.content()
        browser.close()
    return html


def fetch_boxscore(session: Session, external_match_id: int) -> ScrapedMatchBoxScore:
    """
    Render a match page, parse its box score, and upsert player_stats.

    Requires the match to already exist (created by fetch_schedule for its
    competition) — this only fills in stats for a match that's already known,
    matching the real discovery order (schedule first, box score once played).
    """
    html = render_match_page(external_match_id)
    box = parse_match_page(html)

    match = session.scalar(select(Match).where(Match.external_id == str(external_match_id)))
    if match is None:
        raise ValueError(
            f"Match {external_match_id} not found in the database — "
            "run fetch_schedule for its competition first."
        )

    competition = get_or_create_competition(
        session, box.external_competition_id, schedule_url=box.competition_url
    )
    upsert_box_score(session, competition, match, box)
    session.commit()
    return box
