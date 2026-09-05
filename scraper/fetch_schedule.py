"""
Fetches and upserts the fixture list for one competition.

Pipeline step 1 in docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2.

Like the match page, this needs a headless browser — confirmed by sampling a
real competition page ("VRL Prva Liga 2025/26"); see
scraper/parsers/schedule_page.py for the DOM contract and
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.1a for why a plain HTTP GET
doesn't work here.
"""

from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from scraper.db_writer import (
    get_or_create_active_season,
    get_or_create_competition,
    get_or_create_matchday,
    upsert_fixture,
)
from scraper.parsers.schedule_page import parse_schedule_page

_RENDER_TIMEOUT_MS = 15_000


def render_schedule_page(url: str) -> str:
    """Load a competition's schedule page in a headless browser and return the
    fully-rendered HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".tw_competition_round[tw_round_id]", timeout=_RENDER_TIMEOUT_MS)
        html = page.content()
        browser.close()
    return html


def fetch_schedule(session: Session, schedule_url: str, competition_name: str | None = None) -> int:
    """
    Render a competition's schedule page and upsert every fixture found on it.

    Returns the number of fixtures written. Each fixture becomes a `matches`
    row (score/status only — no kickoff time; see db/models.py Match.kickoff_at)
    grouped into a `matchdays` row by the site's own round label. Player-level
    stats are NOT touched here — that's fetch_boxscore.py's job, run per-match
    once a fixture is FINISHED.
    """
    html = render_schedule_page(schedule_url)
    external_competition_id, fixtures = parse_schedule_page(html)

    competition = get_or_create_competition(
        session, external_competition_id, name=competition_name, schedule_url=schedule_url
    )
    season = get_or_create_active_season(session, competition)

    for fixture in fixtures:
        matchday = get_or_create_matchday(session, season, fixture.round_label)
        upsert_fixture(session, matchday, fixture)

    session.commit()
    return len(fixtures)
