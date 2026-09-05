"""
Parses a totalwaterpolo.com match/box-score page into per-player and per-coach
statistics. See module docstring in parsers/schedule_page.py for the isolation
rationale — this file is the only place box-score selectors should appear.

TODO: selectors are not yet implemented — need a sample match page URL to build
against. See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7 (Next Steps).
"""

from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class ScrapedPlayerStat:
    player_name: str
    club: str
    goals: int
    assists: int
    fouls_drawn: int
    steals: int
    blocks: int
    swimoffs_won: int
    misses: int
    personal_fouls: int
    turnovers: int
    offensive_fouls: int
    saves: int
    goals_conceded: int


@dataclass
class ScrapedCoachStat:
    coach_name: str
    club: str
    goals_for: int
    goals_against: int


@dataclass
class ScrapedBoxScore:
    player_stats: list[ScrapedPlayerStat]
    coach_stats: list[ScrapedCoachStat]


def parse_match_page(html: str) -> ScrapedBoxScore:
    """Parse a single match's box-score page into per-player/coach statistics."""
    soup = BeautifulSoup(html, "lxml")  # noqa: F841
    raise NotImplementedError("Selectors pending — see module docstring.")
