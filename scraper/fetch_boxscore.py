"""
Fetches and renders a single match page via headless browser, then parses it.

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

from playwright.sync_api import sync_playwright

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


def fetch_boxscore(external_match_id: int) -> ScrapedMatchBoxScore:
    """
    Render a match page and parse its box score.

    Upserting the result into player_stats/coach_stats (keyed by match_id +
    player_id, resolved via player_resolver) is wired up once the DB session
    layer exists — see docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7
    (Next Steps).
    """
    html = render_match_page(external_match_id)
    return parse_match_page(html)
