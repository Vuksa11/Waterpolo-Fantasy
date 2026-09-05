"""
Parses a totalwaterpolo.com fixture-list page into structured fixtures.

All CSS/XPath selectors for this page type live here and nowhere else — see
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.1. A site redesign should only
ever require changes in this file.

TODO: selectors are not yet implemented — need a sample fixture-list page URL per
competition (Regionalna liga / Super liga Srbije / Prva liga Srbije) to build against.
See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7 (Next Steps).
"""

from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup


@dataclass
class ScrapedFixture:
    external_id: str
    home_club: str
    away_club: str
    home_score: int | None
    away_score: int | None
    status: str  # "UPCOMING" | "LIVE" | "FINISHED"
    kickoff_at: datetime
    match_url: str


def parse_schedule_page(html: str) -> list[ScrapedFixture]:
    """Parse a competition's fixture-list page into a list of ScrapedFixture."""
    soup = BeautifulSoup(html, "lxml")  # noqa: F841
    raise NotImplementedError("Selectors pending — see module docstring.")
